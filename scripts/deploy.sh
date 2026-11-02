#!/usr/bin/env bash
# Deploy the Function App with a read-only system-assigned Managed Identity.
set -euo pipefail

RG=${RG:-rg-gov-bot}
LOC=${LOC:-westus2}
NAME=${NAME:-func-govbot-$RANDOM}
STORAGE=${STORAGE:-stgovbot$RANDOM}
SUB_ID=$(az account show --query id -o tsv)

# --- Infrastructure -------------------------------------------------------
# Tagged so it passes the resource-group deny policy from apply-policy.sh.
az group create -n "$RG" -l "$LOC" \
  --tags owner="${OWNER:-platform-team}" environment=prod costCenter=platform -o none
az storage account create -g "$RG" -n "$STORAGE" --sku Standard_LRS -o none

# Flex Consumption = serverless, scales to zero, you pay per execution.
az functionapp create -g "$RG" -n "$NAME" \
  --storage-account "$STORAGE" \
  --flexconsumption-location "$LOC" \
  --runtime python --runtime-version 3.11 -o none

# --- Identity --------------------------------------------------------------
# System-assigned managed identity: Azure issues and rotates the credential.
PRINCIPAL_ID=$(az functionapp identity assign -g "$RG" -n "$NAME" --query principalId -o tsv)

# Least privilege: Reader covers Resource Graph queries and Azure Monitor metric
# reads. The scanner never writes; tag fixes are made by Azure Policy's own
# identities (scripts/apply-policy.sh), so no custom role is needed.
az role assignment create --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role Reader --scope "/subscriptions/$SUB_ID" -o none

# --- App settings ----------------------------------------------------------
az functionapp config appsettings set -g "$RG" -n "$NAME" -o none --settings \
  GOV_SCHEDULE="0 0 14 * * 1-5" \
  GOV_REQUIRED_TAGS="owner,environment,costCenter" \
  GOV_DRY_RUN=true
# TEAMS_WEBHOOK_URL: put it in Key Vault and use a Key Vault reference:
#   TEAMS_WEBHOOK_URL=@Microsoft.KeyVault(SecretUri=https://<vault>.vault.azure.net/secrets/teams-webhook/)

# --- Code ------------------------------------------------------------------
func azure functionapp publish "$NAME" --python

echo "Deployed $NAME. Trigger manually:"
echo "  az functionapp function keys list -g $RG -n $NAME --function-name scan_now"
