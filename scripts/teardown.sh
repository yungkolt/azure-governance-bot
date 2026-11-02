#!/usr/bin/env bash
# Remove everything the deployment created, in the order that leaves nothing
# behind:
#   1. Disable the Deploy workflow, so the next push to main doesn't recreate it.
#   2. Remove the scanner's subscription-level Reader assignment. It lives
#      outside the resource group, so deleting the group would leave it orphaned
#      (and the scanner would later report it as a stale assignment).
#   3. Delete the resource group: Function App, storage, Key Vault, monitoring,
#      alerts. The managed identity and its Microsoft Graph permission go with it.
#   4. Purge the soft-deleted Key Vault, so a redeploy can reuse its name.
#   5. Optionally remove the pipeline identity and its GitHub configuration.
#
# Usage:
#   REPO=yungkolt/azure-governance-bot ./scripts/teardown.sh
#   REPO=... REMOVE_PIPELINE=1 ./scripts/teardown.sh   # also remove the OIDC identity
#
# Redeploy later: gh workflow enable Deploy && gh workflow run Deploy
# (after REMOVE_PIPELINE=1, run setup-github-oidc.sh first).
set -euo pipefail

RG=${RG:-rg-gov-bot}
REPO=${REPO:-}
REMOVE_PIPELINE=${REMOVE_PIPELINE:-0}
SUB_ID=$(az account show --query id -o tsv)
SCOPE="/subscriptions/$SUB_ID"
HAVE_GH=0
command -v gh >/dev/null && gh auth status >/dev/null 2>&1 && HAVE_GH=1

echo "Subscription: $(az account show --query name -o tsv) ($SUB_ID)"
echo "Resource group: $RG"
read -r -p "Delete everything listed above? [y/N] " answer
[[ "$answer" =~ ^[Yy]$ ]] || { echo "Cancelled."; exit 0; }

# --- 1. Stop continuous deployment ------------------------------------------
if [[ -n "$REPO" && $HAVE_GH -eq 1 ]]; then
  gh workflow disable Deploy -R "$REPO" && echo "Disabled the Deploy workflow"
else
  echo "Skipping workflow disable (set REPO and log in with gh). Disable it in the Actions tab."
fi

# --- 2-4. Azure resources ----------------------------------------------------
if az group show -n "$RG" >/dev/null 2>&1; then
  VAULTS=$(az keyvault list -g "$RG" --query "[].name" -o tsv)

  for APP in $(az functionapp list -g "$RG" --query "[].name" -o tsv); do
    PRINCIPAL=$(az functionapp identity show -g "$RG" -n "$APP" --query principalId -o tsv 2>/dev/null || true)
    if [[ -n "$PRINCIPAL" ]]; then
      az role assignment delete --assignee "$PRINCIPAL" --scope "$SCOPE" -o none || true
      echo "Removed subscription role assignments for $APP"
    fi
  done

  echo "Deleting resource group $RG (a few minutes)..."
  az group delete -n "$RG" --yes
  echo "Deleted $RG"

  for VAULT in $VAULTS; do
    az keyvault purge -n "$VAULT" && echo "Purged soft-deleted Key Vault $VAULT" || true
  done
else
  echo "Resource group $RG not found; nothing to delete in Azure"
fi

# --- 5. Pipeline identity (optional) -----------------------------------------
if [[ "$REMOVE_PIPELINE" == "1" ]]; then
  [[ -n "$REPO" ]] || { echo "REMOVE_PIPELINE needs REPO" >&2; exit 1; }
  APP_NAME="gh-${REPO//\//-}"
  APP_ID=$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv)
  if [[ -n "$APP_ID" ]]; then
    SP_ID=$(az ad sp show --id "$APP_ID" --query id -o tsv 2>/dev/null || true)
    [[ -n "$SP_ID" ]] && az role assignment delete --assignee "$SP_ID" --scope "$SCOPE" -o none || true
    az ad app delete --id "$APP_ID"
    echo "Deleted app registration $APP_NAME and its role assignments"
  fi
  if [[ $HAVE_GH -eq 1 ]]; then
    for VAR in AZURE_CLIENT_ID AZURE_TENANT_ID AZURE_SUBSCRIPTION_ID GOV_RBAC_ALLOWED_PRINCIPALS; do
      gh variable delete "$VAR" -R "$REPO" 2>/dev/null || true
    done
    gh api --method DELETE "repos/$REPO/environments/production" --silent 2>/dev/null || true
    echo "Removed GitHub variables and the production environment"
  fi
fi

cat <<EOF

Teardown complete. Check nothing is left:
  az group list --query "[].name" -o tsv
  python -m governance.cli            # no stale-role-assignment for the removed identity
EOF
