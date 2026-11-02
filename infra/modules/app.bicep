// Resource-group resources for the Azure Governance Bot.
//
// Identity model: the Function App's system-assigned managed identity is the
// only principal. It reaches storage, Key Vault and Application Insights with
// Entra ID tokens; shared keys on the storage account are disabled.

param location string
param namePrefix string
param tags object
param alertEmail string
@secure()
param teamsWebhookUrl string
param rbacAllowedPrincipals string
param schedule string

var token = take(uniqueString(resourceGroup().id), 8)
var functionAppName = 'func-${namePrefix}-${token}'
var deploymentContainer = 'app-package'
var reportsContainer = 'reports'

// Built-in role definition IDs (identical in every tenant)
var storageBlobDataOwner = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
var keyVaultSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'

// --- Storage: function host state, deployment package, report history -------

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'st${namePrefix}${token}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }

  resource blob 'blobServices' = {
    name: 'default'

    resource deployment 'containers' = {
      name: deploymentContainer
      properties: { publicAccess: 'None' }
    }

    resource reports 'containers' = {
      name: reportsContainer
      properties: { publicAccess: 'None' }
    }
  }
}

// --- Monitoring --------------------------------------------------------------

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${namePrefix}-${token}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${namePrefix}-${token}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
  }
}

// --- Key Vault: the Teams webhook URL is a secret, never a plain setting ------

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-${namePrefix}-${token}'
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

resource teamsSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(teamsWebhookUrl)) {
  parent: vault
  name: 'teams-webhook'
  properties: { value: teamsWebhookUrl }
}

// --- Function App (Flex Consumption) ----------------------------------------

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: 'plan-${namePrefix}-${token}'
  location: location
  tags: tags
  kind: 'functionapp'
  sku: { tier: 'FlexConsumption', name: 'FC1' }
  properties: { reserved: true }
}

resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: functionAppName
  location: location
  tags: tags
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
    }
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}${deploymentContainer}'
          authentication: { type: 'SystemAssignedIdentity' }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 40
        instanceMemoryMB: 2048
      }
      runtime: { name: 'python', version: '3.11' }
    }
  }
}

// App settings are a child resource so they can reference the identity and
// the Key Vault URI. Flex Consumption sets the runtime in functionAppConfig, so
// FUNCTIONS_WORKER_RUNTIME is intentionally absent.
resource appSettings 'Microsoft.Web/sites/config@2024-04-01' = {
  parent: functionApp
  name: 'appsettings'
  properties: union({
    AzureWebJobsStorage__accountName: storage.name
    APPLICATIONINSIGHTS_CONNECTION_STRING: appInsights.properties.ConnectionString
    GOV_SCHEDULE: schedule
    GOV_SUBSCRIPTION_IDS: subscription().subscriptionId
    GOV_REQUIRED_TAGS: 'owner,environment,costCenter'
    GOV_RBAC_ALLOWED_PRINCIPALS: rbacAllowedPrincipals
    GOV_REPORT_STORAGE_URL: storage.properties.primaryEndpoints.blob
    GOV_REPORT_CONTAINER: reportsContainer
    GOV_DRY_RUN: 'true'
  }, empty(teamsWebhookUrl) ? {} : {
    TEAMS_WEBHOOK_URL: '@Microsoft.KeyVault(SecretUri=${vault.properties.vaultUri}secrets/teams-webhook/)'
  })
}

// --- Role assignments for the Function App identity -------------------------

// Host state, deployment package and report history all live in this account.
resource storageOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, functionApp.id, storageBlobDataOwner)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataOwner)
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource vaultReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, functionApp.id, keyVaultSecretsUser)
  scope: vault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUser)
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// --- Alerts ------------------------------------------------------------------

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = if (!empty(alertEmail)) {
  name: 'ag-${namePrefix}-${token}'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: 'govbot'
    enabled: true
    emailReceivers: [
      { name: 'owner', emailAddress: alertEmail, useCommonAlertSchema: true }
    ]
  }
}

var alertActions = empty(alertEmail) ? {} : { actionGroups: [actionGroup.id] }

// Any failed invocation in the last hour.
resource failedRunAlert 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-${namePrefix}-failed-run'
  location: location
  tags: tags
  properties: {
    displayName: 'Governance bot: failed run'
    description: 'A scan invocation failed. Check Application Insights for the exception.'
    severity: 2
    enabled: true
    scopes: [appInsights.id]
    evaluationFrequency: 'PT1H'
    windowSize: 'PT1H'
    criteria: {
      allOf: [
        {
          query: 'requests | where success == false'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
        }
      ]
    }
    actions: alertActions
  }
}

// No successful scheduled scan in two days: catches a broken schedule,
// a lost role assignment or an app that stopped starting.
resource missedRunAlert 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: 'alert-${namePrefix}-missed-run'
  location: location
  tags: tags
  properties: {
    displayName: 'Governance bot: no successful scan in 2 days'
    description: 'The scheduled scan has not completed successfully for 48 hours.'
    severity: 2
    enabled: true
    scopes: [appInsights.id]
    evaluationFrequency: 'PT6H'
    windowSize: 'P2D'
    criteria: {
      allOf: [
        {
          query: 'requests | where name == "scheduled_scan" and success == true'
          timeAggregation: 'Count'
          operator: 'LessThan'
          threshold: 1
          failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
        }
      ]
    }
    actions: alertActions
  }
}

output functionAppName string = functionApp.name
output functionAppHostName string = functionApp.properties.defaultHostName
output principalId string = functionApp.identity.principalId
output keyVaultName string = vault.name
output storageAccountName string = storage.name
