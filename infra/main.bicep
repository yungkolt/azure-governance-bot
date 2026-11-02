// Azure Governance Bot: full deployment at subscription scope.
//
// Subscription scope is required because the scanner's Reader role is granted
// on the subscription itself, outside the resource group being created.
//
//   az deployment sub create -l westus2 -f infra/main.bicep -p infra/main.bicepparam

targetScope = 'subscription'

@description('Azure region for every resource.')
param location string = 'westus2'

@description('Resource group to create for the bot.')
param resourceGroupName string = 'rg-gov-bot'

@description('Lowercase letters and digits, 3-11 characters. Used in resource names.')
@minLength(3)
@maxLength(11)
param namePrefix string = 'govbot'

@description('Value for the owner tag. Satisfies the resource-group deny policy.')
param owner string

@description('Email for failure alerts. Leave empty to create the alert rules without notifications.')
param alertEmail string = ''

@description('Teams Workflow webhook URL. Stored in Key Vault; never in app settings.')
@secure()
param teamsWebhookUrl string = ''

@description('Comma-separated principal object IDs exempt from the broad-role check, e.g. the deployment identity.')
param rbacAllowedPrincipals string = ''

@description('NCRONTAB schedule (UTC). Daily, so the missed-run alert has a simple rule.')
param schedule string = '0 0 14 * * *'

var tags = {
  owner: owner
  environment: 'prod'
  costCenter: 'platform'
  workload: 'azure-governance-bot'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module app 'modules/app.bicep' = {
  scope: rg
  name: 'governance-bot-app'
  params: {
    location: location
    namePrefix: toLower(namePrefix)
    tags: tags
    alertEmail: alertEmail
    teamsWebhookUrl: teamsWebhookUrl
    rbacAllowedPrincipals: rbacAllowedPrincipals
    schedule: schedule
  }
}

// Reader on the subscription: inventory (Resource Graph), metrics (Azure
// Monitor), role assignments and cost data. The scanner holds nothing else.
var readerRoleId = 'acdd72a7-3385-48ef-bd42-f606fba81ae7'

resource scannerReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, resourceGroupName, namePrefix, readerRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRoleId)
    principalId: app.outputs.principalId
    principalType: 'ServicePrincipal'
    description: 'Azure Governance Bot: read-only scanner'
  }
}

output resourceGroupName string = rg.name
output functionAppName string = app.outputs.functionAppName
output functionAppHostName string = app.outputs.functionAppHostName
output principalId string = app.outputs.principalId
output keyVaultName string = app.outputs.keyVaultName
output storageAccountName string = app.outputs.storageAccountName
