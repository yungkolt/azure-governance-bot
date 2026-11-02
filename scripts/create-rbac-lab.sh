#!/usr/bin/env bash
# Create identity and access findings in your own tenant, at no cost:
#   - a DISABLED user holding Contributor at subscription scope
#       -> broad-role-assignment (Medium) and stale-role-assignment (disabled user)
#   - a user given Reader, then DELETED, leaving an orphaned assignment
#       -> stale-role-assignment (deleted principal)
#   - a custom role granting Microsoft.Compute/*
#       -> custom-role-wildcard (Medium)
#
# The disabled user's password is random and never shown; the account cannot
# sign in. Requires User Administrator (or Global Administrator) in the tenant.
# Remove everything with ./scripts/remove-rbac-lab.sh
set -euo pipefail

SUB_ID=$(az account show --query id -o tsv)
SCOPE="/subscriptions/$SUB_ID"
STATE=.rbac-lab.env
DOMAIN=$(az rest --method GET --url "https://graph.microsoft.com/v1.0/domains" \
  --query "value[?isDefault].id | [0]" -o tsv)
SUFFIX=$RANDOM

new_user() {
  az ad user create --display-name "$1" --user-principal-name "$2@$DOMAIN" \
    --password "$(openssl rand -base64 24)Aa1!" --force-change-password-next-sign-in true \
    --query id -o tsv
}

# Retry role assignment while a new user replicates through Entra ID.
assign() {
  for attempt in 1 2 3 4 5 6; do
    if az role assignment create --assignee-object-id "$1" --assignee-principal-type User \
         --role "$2" --scope "$SCOPE" -o none 2>/dev/null; then
      return 0
    fi
    [[ $attempt -eq 6 ]] && { echo "Role assignment failed for $1" >&2; return 1; }
    sleep 10
  done
}

# 1) Disabled user with a standing Contributor assignment
DISABLED_ID=$(new_user "Gov Lab Disabled" "gov-lab-disabled-$SUFFIX")
az ad user update --id "$DISABLED_ID" --account-enabled false
assign "$DISABLED_ID" "Contributor"
echo "Created disabled user with Contributor at subscription scope"

# 2) User with Reader, then deleted: the assignment stays behind
DELETED_ID=$(new_user "Gov Lab Deleted" "gov-lab-deleted-$SUFFIX")
assign "$DELETED_ID" "Reader"
DELETED_ASSIGNMENT=$(az role assignment list --assignee "$DELETED_ID" --scope "$SCOPE" \
  --query "[0].id" -o tsv)
az ad user delete --id "$DELETED_ID"
echo "Created and deleted a user, leaving its Reader assignment orphaned"

# 3) Custom role with a provider-wide wildcard
ROLE_NAME="Gov Lab Compute Operator $SUFFIX"
az role definition create -o none --role-definition "{
  \"Name\": \"$ROLE_NAME\",
  \"Description\": \"Lab role with a provider-wide wildcard\",
  \"Actions\": [\"Microsoft.Compute/*\"],
  \"AssignableScopes\": [\"$SCOPE\"]
}"
echo "Created custom role '$ROLE_NAME'"

cat > "$STATE" <<EOF
SCOPE=$SCOPE
DISABLED_ID=$DISABLED_ID
DELETED_ASSIGNMENT=$DELETED_ASSIGNMENT
ROLE_NAME="$ROLE_NAME"
EOF

echo
echo "Wait a few minutes for Resource Graph to index the changes, then run:"
echo "  python -m governance.cli -v"
