#!/usr/bin/env bash
# Grant the deployed Function App's managed identity read access to Microsoft
# Graph, for the stale role-assignment check and principal display names.
#
# Azure RBAC and Entra ID are separate permission systems:
#   - Azure RBAC roles (Reader) govern Azure resources.
#   - Microsoft Graph app roles (Directory.Read.All) govern directory data.
# A managed identity has no Graph permissions until an app role is assigned,
# which requires Privileged Role Administrator or Global Administrator.
#
# Usage: RG=rg-gov-bot NAME=<function-app-name> ./scripts/grant-graph-permissions.sh
#
# Not needed for local runs: the CLI's `az login` token is used instead.
set -euo pipefail

: "${RG:?Set RG to the resource group of the Function App}"
: "${NAME:?Set NAME to the Function App name}"
PERMISSION=${PERMISSION:-Directory.Read.All}   # least privilege for directoryObjects/getByIds
GRAPH_APP_ID=00000003-0000-0000-c000-000000000000   # Microsoft Graph, same in every tenant

MI_ID=$(az functionapp identity show -g "$RG" -n "$NAME" --query principalId -o tsv)
[[ -n "$MI_ID" ]] || { echo "No system-assigned identity on $NAME" >&2; exit 1; }

GRAPH_SP_ID=$(az ad sp show --id "$GRAPH_APP_ID" --query id -o tsv)
ROLE_ID=$(az ad sp show --id "$GRAPH_APP_ID" \
  --query "appRoles[?value=='$PERMISSION' && contains(allowedMemberTypes, 'Application')].id | [0]" \
  -o tsv)
[[ -n "$ROLE_ID" ]] || { echo "Graph app role not found: $PERMISSION" >&2; exit 1; }

EXISTING=$(az rest --method GET \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$MI_ID/appRoleAssignments" \
  --query "value[?appRoleId=='$ROLE_ID'] | length(@)" -o tsv)

if [[ "$EXISTING" != "0" ]]; then
  echo "$NAME already has $PERMISSION"
  exit 0
fi

az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$MI_ID/appRoleAssignments" \
  --headers "Content-Type=application/json" \
  --body "{\"principalId\": \"$MI_ID\", \"resourceId\": \"$GRAPH_SP_ID\", \"appRoleId\": \"$ROLE_ID\"}" \
  -o none

echo "Granted $PERMISSION to $NAME's managed identity ($MI_ID)."
echo "Token caches can take a few minutes to pick up the new permission."
