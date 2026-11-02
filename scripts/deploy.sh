#!/usr/bin/env bash
# Deploy from your machine: the same Bicep template the GitHub pipeline uses,
# then publish the code with Azure Functions Core Tools.
#
#   GOV_OWNER=you GOV_ALERT_EMAIL=you@example.com ./scripts/deploy.sh
#
# Optional: TEAMS_WEBHOOK_URL (stored in Key Vault), AZURE_LOCATION.
set -euo pipefail

export AZURE_LOCATION=${AZURE_LOCATION:-westus2}

echo "Deploying infrastructure..."
OUTPUTS=$(az deployment sub create \
  --name "governance-bot-$(date +%Y%m%d%H%M%S)" \
  --location "$AZURE_LOCATION" \
  --template-file infra/main.bicep \
  --parameters infra/main.bicepparam \
  --query properties.outputs -o json)

RG=$(jq -r .resourceGroupName.value <<<"$OUTPUTS")
APP=$(jq -r .functionAppName.value <<<"$OUTPUTS")
echo "Infrastructure ready: $APP in $RG"

echo "Publishing code..."
func azure functionapp publish "$APP" --python

cat <<EOF

Deployed $APP.
Grant Microsoft Graph access once, for the identity checks:
  RG=$RG NAME=$APP ./scripts/grant-graph-permissions.sh
Run a scan now:
  KEY=\$(az functionapp function keys list -g $RG -n $APP --function-name scan_now --query default -o tsv)
  curl "https://\$(az functionapp show -g $RG -n $APP --query defaultHostName -o tsv)/api/scan?code=\$KEY"
Remove everything:
  az group delete -n $RG --yes
EOF
