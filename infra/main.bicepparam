using 'main.bicep'

// Values here are not secret. The Teams webhook URL is passed on the command
// line or from a GitHub secret, never committed:
//   az deployment sub create ... -p infra/main.bicepparam -p teamsWebhookUrl=$TEAMS_WEBHOOK_URL

param location = readEnvironmentVariable('AZURE_LOCATION', 'westus2')
param owner = readEnvironmentVariable('GOV_OWNER', 'platform-team')
param alertEmail = readEnvironmentVariable('GOV_ALERT_EMAIL', '')
param rbacAllowedPrincipals = readEnvironmentVariable('GOV_RBAC_ALLOWED_PRINCIPALS', '')
param teamsWebhookUrl = readEnvironmentVariable('TEAMS_WEBHOOK_URL', '')
