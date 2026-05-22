// =============================================================================
// Function App (Flex Consumption, Python 3.11) + dedicated operational storage
//
// Hosts the Durable Functions orchestrator for the translation pipeline:
//   Extract → Translate Pass 1 → Guardrails → Judge → Revise? → Reconstruct
//
// Uses the workload's user-assigned managed identity for ALL connections —
// AzureWebJobsStorage, Cosmos, Foundry. No keys.
// =============================================================================
param functionAppName string
param planName string
param funcStorageName string
param location string
param tags object

@description('Resource ID of the workload user-assigned managed identity')
param miId string
param miPrincipalId string
param miClientId string

param appInsightsConnectionString string
param foundryEndpoint string
param cosmosEndpoint string
param cosmosDatabaseName string
param documentStorageBlobEndpoint string

// ----------------------------------------------------------------------------
// Operational storage for the Functions runtime (separate from document storage)
// ----------------------------------------------------------------------------
resource funcStorage 'Microsoft.Storage/storageAccounts@2024-01-01' = {
  name: funcStorageName
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowSharedKeyAccess: false        // Entra-only
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Enabled'     // flip after PE in Phase 5
    networkAcls: { defaultAction: 'Allow', bypass: 'AzureServices' }
  }
}

resource funcBlob 'Microsoft.Storage/storageAccounts/blobServices@2024-01-01' = {
  parent: funcStorage
  name: 'default'
}

// Flex Consumption requires a blob container for deployment packages
resource deploymentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2024-01-01' = {
  parent: funcBlob
  name: 'deployment'
  properties: { publicAccess: 'None' }
}

// ----------------------------------------------------------------------------
// RBAC: workload MI needs full data-plane on the operational storage
// (Functions host writes blobs, queues, and tables for Durable + bindings)
// ----------------------------------------------------------------------------
var roleStorageBlobDataOwner         = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
var roleStorageQueueDataContributor  = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
var roleStorageTableDataContributor  = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'

resource mi_blobOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(funcStorage.id, miPrincipalId, roleStorageBlobDataOwner)
  scope: funcStorage
  properties: {
    principalId: miPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleStorageBlobDataOwner)
  }
}

resource mi_queueContrib 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(funcStorage.id, miPrincipalId, roleStorageQueueDataContributor)
  scope: funcStorage
  properties: {
    principalId: miPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleStorageQueueDataContributor)
  }
}

resource mi_tableContrib 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(funcStorage.id, miPrincipalId, roleStorageTableDataContributor)
  scope: funcStorage
  properties: {
    principalId: miPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleStorageTableDataContributor)
  }
}

// ----------------------------------------------------------------------------
// Flex Consumption plan + Function App
// ----------------------------------------------------------------------------
resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: planName
  location: location
  tags: tags
  sku: { name: 'FC1', tier: 'FlexConsumption' }
  kind: 'functionapp'
  properties: { reserved: true }
}

resource func 'Microsoft.Web/sites@2024-04-01' = {
  name: functionAppName
  location: location
  tags: tags
  kind: 'functionapp,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${miId}': {} }
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    publicNetworkAccess: 'Enabled'    // flip after PE in Phase 5
    keyVaultReferenceIdentity: miId
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${funcStorage.properties.primaryEndpoints.blob}deployment'
          authentication: {
            type: 'UserAssignedIdentity'
            userAssignedIdentityResourceId: miId
          }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 100
        instanceMemoryMB: 2048
      }
      runtime: {
        name: 'python'
        version: '3.11'
      }
    }
    siteConfig: {
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      appSettings: [
        // Functions runtime: MI-based connection to operational storage
        { name: 'AzureWebJobsStorage__accountName', value: funcStorage.name }
        { name: 'AzureWebJobsStorage__credential',  value: 'managedidentity' }
        { name: 'AzureWebJobsStorage__clientId',    value: miClientId }

        // Telemetry
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }

        // Default credential for all Azure SDK clients (DefaultAzureCredential picks this up)
        { name: 'AZURE_CLIENT_ID', value: miClientId }

        // Workload endpoints
        { name: 'FOUNDRY_ENDPOINT',                value: foundryEndpoint }
        { name: 'COSMOS_ENDPOINT',                 value: cosmosEndpoint }
        { name: 'COSMOS_DATABASE',                 value: cosmosDatabaseName }
        { name: 'DOCUMENT_STORAGE_BLOB_ENDPOINT',  value: documentStorageBlobEndpoint }

        // Model deployment names — keep aligned with aiFoundry.bicep
        { name: 'MODEL_TRANSLATOR', value: 'gpt-4-1' }
        { name: 'MODEL_JUDGE',      value: 'grok-3' }
        { name: 'MODEL_UTILITY',    value: 'gpt-4o-mini' }
      ]
    }
  }
  dependsOn: [
    mi_blobOwner
    mi_queueContrib
    mi_tableContrib
  ]
}

output functionAppName string = func.name
output functionAppHostname string = func.properties.defaultHostName
output funcStorageName string = funcStorage.name
