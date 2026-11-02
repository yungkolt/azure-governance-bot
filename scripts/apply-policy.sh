#!/usr/bin/env bash
# Assign Azure Policy to prevent and auto-fix tagging gaps at subscription scope.
#
#   1. Deny:   resource groups cannot be created or updated without an `owner` tag.
#   2. Modify: resources inherit `owner`, `environment` and `costCenter` from their
#              resource group when they don't set them, on create and update.
#   3. Remediate: existing non-compliant resources are fixed by remediation tasks.
#
# The scanner keeps its read-only Reader role. Tag writes are performed by each
# Modify assignment's own managed identity, which receives the roles the policy
# definition declares in roleDefinitionIds (or POLICY_ROLE if set).
#
# Usage:
#   ./scripts/apply-policy.sh                          # enforce
#   ENFORCEMENT=DoNotEnforce ./scripts/apply-policy.sh # evaluate compliance only
#   POLICY_ROLE="Tag Contributor" ./scripts/apply-policy.sh  # override the identity role
# Remove everything with ./scripts/remove-policy.sh
set -euo pipefail

SUB_ID=$(az account show --query id -o tsv)
SCOPE="/subscriptions/$SUB_ID"
LOCATION=${LOCATION:-westus2}              # where the assignments' identities live
ENFORCEMENT=${ENFORCEMENT:-Default}        # Default = enforce, DoNotEnforce = audit only
INHERITED_TAGS=${INHERITED_TAGS:-"owner environment costCenter"}
REQUIRED_RG_TAG=${REQUIRED_RG_TAG:-owner}

# Built-in definitions are looked up by display name, not hardcoded GUIDs,
# so the script fails loudly if Microsoft ever renames one.
definition_id() {
  local id
  id=$(az policy definition list --query "[?displayName=='$1'].name | [0]" -o tsv)
  if [[ -z "$id" ]]; then
    echo "Built-in policy not found: $1" >&2
    exit 1
  fi
  echo "$id"
}

REQUIRE_RG_TAG=$(definition_id "Require a tag on resource groups")
INHERIT_TAG=$(definition_id "Inherit a tag from the resource group if missing")

# Roles the Modify identity needs, as declared by the definition itself.
if [[ -n "${POLICY_ROLE:-}" ]]; then
  ROLES=("$POLICY_ROLE")
else
  mapfile -t ROLES < <(az policy definition show --name "$INHERIT_TAG" \
    --query "policyRule.then.details.roleDefinitionIds[]" -o tsv | sed 's#.*/##')
fi
ROLE_NAMES=$(for r in "${ROLES[@]}"; do
  az role definition list --name "$r" --query "[0].roleName" -o tsv 2>/dev/null || echo "$r"
done | paste -sd, -)

echo "Subscription: $SUB_ID   Enforcement: $ENFORCEMENT"
echo "Modify identity role(s): $ROLE_NAMES"

# --- 1. Deny resource groups without an owner tag ---------------------------
az policy assignment create \
  --name "require-rg-${REQUIRED_RG_TAG,,}" \
  --display-name "Require '$REQUIRED_RG_TAG' tag on resource groups" \
  --policy "$REQUIRE_RG_TAG" \
  --scope "$SCOPE" \
  --enforcement-mode "$ENFORCEMENT" \
  --params "{\"tagName\": {\"value\": \"$REQUIRED_RG_TAG\"}}" \
  -o none
echo "Assigned: deny resource groups without '$REQUIRED_RG_TAG'"

# --- 2. Inherit tags from the resource group (Modify) -----------------------
for TAG in $INHERITED_TAGS; do
  NAME="inherit-${TAG,,}"
  PRINCIPAL_ID=$(az policy assignment create \
    --name "$NAME" \
    --display-name "Inherit '$TAG' tag from resource group" \
    --policy "$INHERIT_TAG" \
    --scope "$SCOPE" \
    --enforcement-mode "$ENFORCEMENT" \
    --params "{\"tagName\": {\"value\": \"$TAG\"}}" \
    --mi-system-assigned --location "$LOCATION" \
    --query identity.principalId -o tsv)

  # Grant the identity its role(s). Retry while the new identity propagates
  # in Entra ID, which can take a minute.
  for ROLE in "${ROLES[@]}"; do
    for attempt in 1 2 3 4 5 6; do
      if az role assignment create \
           --assignee-object-id "$PRINCIPAL_ID" \
           --assignee-principal-type ServicePrincipal \
           --role "$ROLE" --scope "$SCOPE" -o none 2>/dev/null; then
        break
      fi
      [[ $attempt -eq 6 ]] && { echo "Role assignment failed for $NAME" >&2; exit 1; }
      sleep 10
    done
  done
  echo "Assigned: inherit '$TAG' (identity granted $ROLE_NAMES)"
done

# --- 3. Remediate existing resources ----------------------------------------
# New assignments only affect resources created or updated from now on.
# Remediation tasks apply the Modify effect to resources that already exist.
if [[ "$ENFORCEMENT" == "Default" ]]; then
  for TAG in $INHERITED_TAGS; do
    NAME="inherit-${TAG,,}"
    az policy remediation create \
      --name "remediate-$NAME-$(date +%Y%m%d%H%M)" \
      --policy-assignment "$SCOPE/providers/Microsoft.Authorization/policyAssignments/$NAME" \
      --resource-discovery-mode ReEvaluateCompliance \
      -o none
    echo "Started remediation: $NAME"
  done
fi

cat <<EOF

Done. Notes:
- Assignments take up to 30 minutes to take effect.
- View compliance: Azure portal > Policy > Compliance
- Check remediation: az policy remediation list -o table
EOF
