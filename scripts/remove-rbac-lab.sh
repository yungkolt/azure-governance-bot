#!/usr/bin/env bash
# Remove everything created by create-rbac-lab.sh.
set -euo pipefail

STATE=.rbac-lab.env
[[ -f "$STATE" ]] || { echo "No $STATE found; nothing to remove." >&2; exit 0; }
# shellcheck source=/dev/null
source "$STATE"

az role assignment delete --assignee "$DISABLED_ID" --scope "$SCOPE" -o none || true
az ad user delete --id "$DISABLED_ID" || true
echo "Removed disabled user and its role assignment"

# The deleted user's assignment can only be removed by its assignment ID.
az role assignment delete --ids "$DELETED_ASSIGNMENT" -o none || true
echo "Removed orphaned role assignment"

az role definition delete --name "$ROLE_NAME" --scope "$SCOPE" -o none || true
echo "Removed custom role '$ROLE_NAME'"

rm -f "$STATE"
