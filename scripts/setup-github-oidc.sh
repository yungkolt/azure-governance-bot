#!/usr/bin/env bash
# One-time setup so GitHub Actions can deploy with OpenID Connect: no client
# secret is created, stored or rotated.
#
#   1. App registration + service principal for the pipeline.
#   2. Federated credential trusting only this repo's `production` environment.
#   3. Roles on the subscription:
#        Contributor                               - deploy resources
#        Role Based Access Control Administrator   - create role assignments,
#          CONSTRAINED by a condition to the three roles the template grants
#          (Reader, Storage Blob Data Owner, Key Vault Secrets User). The
#          pipeline cannot use it to grant Owner or itself more access.
#   4. GitHub environment and variables (requires the gh CLI, logged in).
#
# Usage: REPO=<github-user>/azure-governance-bot ./scripts/setup-github-oidc.sh
set -euo pipefail

: "${REPO:?Set REPO to owner/name, e.g. yungkolt/azure-governance-bot}"
ENVIRONMENT=${ENVIRONMENT:-production}
APP_NAME="gh-${REPO//\//-}"
SUB_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)
SCOPE="/subscriptions/$SUB_ID"

# --- 1. App registration and service principal (idempotent) -----------------
APP_ID=$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv)
if [[ -z "$APP_ID" ]]; then
  APP_ID=$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)
  echo "Created app registration $APP_NAME"
fi
SP_ID=$(az ad sp show --id "$APP_ID" --query id -o tsv 2>/dev/null || true)
if [[ -z "$SP_ID" ]]; then
  SP_ID=$(az ad sp create --id "$APP_ID" --query id -o tsv)
fi

# --- 2. Federated credential -------------------------------------------------
SUBJECT="repo:$REPO:environment:$ENVIRONMENT"
EXISTING=$(az ad app federated-credential list --id "$APP_ID" \
  --query "[?subject=='$SUBJECT'] | length(@)" -o tsv)
if [[ "$EXISTING" == "0" ]]; then
  az ad app federated-credential create --id "$APP_ID" -o none --parameters "{
    \"name\": \"github-$ENVIRONMENT\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"$SUBJECT\",
    \"audiences\": [\"api://AzureADTokenExchange\"]
  }"
  echo "Trusting GitHub tokens for $SUBJECT"
fi

# --- 3. Roles ------------------------------------------------------------------
assign() {   # role, [condition]
  for attempt in 1 2 3 4 5 6; do
    if [[ -n "${2:-}" ]]; then
      az role assignment create --assignee-object-id "$SP_ID" --assignee-principal-type ServicePrincipal \
        --role "$1" --scope "$SCOPE" --condition "$2" --condition-version 2.0 -o none 2>/dev/null && return 0
    else
      az role assignment create --assignee-object-id "$SP_ID" --assignee-principal-type ServicePrincipal \
        --role "$1" --scope "$SCOPE" -o none 2>/dev/null && return 0
    fi
    [[ $attempt -eq 6 ]] && { echo "Could not assign $1" >&2; return 1; }
    sleep 10   # new service principals take a moment to replicate
  done
}

READER=acdd72a7-3385-48ef-bd42-f606fba81ae7
BLOB_OWNER=b7e6dc6d-f1e8-4753-8033-0f276bb0955b
KV_SECRETS_USER=4633458b-17de-408a-b874-0445c86b69e6
ALLOWED="$READER, $BLOB_OWNER, $KV_SECRETS_USER"
CONDITION="((!(ActionMatches{'Microsoft.Authorization/roleAssignments/write'})) OR \
(@Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {$ALLOWED})) \
AND ((!(ActionMatches{'Microsoft.Authorization/roleAssignments/delete'})) OR \
(@Resource[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {$ALLOWED}))"

assign "Contributor"
assign "Role Based Access Control Administrator" "$CONDITION"
echo "Granted Contributor and constrained RBAC Administrator on $SCOPE"

# --- 4. GitHub environment and variables ------------------------------------
if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  gh api --method PUT "repos/$REPO/environments/$ENVIRONMENT" --silent
  gh variable set AZURE_CLIENT_ID       -R "$REPO" -b "$APP_ID"
  gh variable set AZURE_TENANT_ID       -R "$REPO" -b "$TENANT_ID"
  gh variable set AZURE_SUBSCRIPTION_ID -R "$REPO" -b "$SUB_ID"
  # The pipeline legitimately holds broad roles; exempt it from the scanner's
  # broad-role check. Add other IDs (comma-separated) if needed.
  gh variable set GOV_RBAC_ALLOWED_PRINCIPALS -R "$REPO" -b "$SP_ID"
  echo "Configured GitHub environment '$ENVIRONMENT' and variables for $REPO"
else
  cat <<EOF
gh CLI not available or not logged in. Create environment '$ENVIRONMENT' in the
repository settings, then add these repository variables:
  AZURE_CLIENT_ID=$APP_ID
  AZURE_TENANT_ID=$TENANT_ID
  AZURE_SUBSCRIPTION_ID=$SUB_ID
  GOV_RBAC_ALLOWED_PRINCIPALS=$SP_ID
EOF
fi

cat <<EOF

Optional repository variables: GOV_OWNER, GOV_ALERT_EMAIL, AZURE_LOCATION.
Optional secret:               TEAMS_WEBHOOK_URL
Then run the Deploy workflow (Actions tab, or push to main).
After the first deploy, grant Microsoft Graph access once:
  RG=rg-gov-bot NAME=<functionAppName from the deploy log> ./scripts/grant-graph-permissions.sh
EOF
