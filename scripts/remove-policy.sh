#!/usr/bin/env bash
# Remove the policy assignments created by apply-policy.sh, and the role
# assignments held by their managed identities. Tags already applied remain.
set -euo pipefail

SUB_ID=$(az account show --query id -o tsv)
SCOPE="/subscriptions/$SUB_ID"
INHERITED_TAGS=${INHERITED_TAGS:-"owner environment costCenter"}
REQUIRED_RG_TAG=${REQUIRED_RG_TAG:-owner}

for TAG in $INHERITED_TAGS; do
  NAME="inherit-${TAG,,}"
  PRINCIPAL_ID=$(az policy assignment show --name "$NAME" --scope "$SCOPE" \
                   --query identity.principalId -o tsv 2>/dev/null || true)
  if [[ -n "$PRINCIPAL_ID" ]]; then
    # Remove its roles first: deleting the assignment deletes its identity,
    # which would leave orphaned role assignments behind.
    az role assignment delete --assignee "$PRINCIPAL_ID" --scope "$SCOPE" -o none || true
    az policy assignment delete --name "$NAME" --scope "$SCOPE" -o none
    echo "Removed: $NAME"
  fi
done

az policy assignment delete --name "require-rg-${REQUIRED_RG_TAG,,}" --scope "$SCOPE" -o none \
  2>/dev/null && echo "Removed: require-rg-${REQUIRED_RG_TAG,,}" || true
