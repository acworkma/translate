// ADLS Gen2 storage account for documents and workflow artifacts
param name string
param location string
param tags object
param miPrincipalId string

resource sa 'Microsoft.Storage/storageAccounts@2024-01-01' = {
  name: name
  location: location
  tags: tags
  sku: { name: 'Standard_GZRS' }
  kind: 'StorageV2'
  identity: { type: 'SystemAssigned' }
  properties: {
    isHnsEnabled: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false        // Entra-only auth — no keys
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Enabled'      // flip to 'Disabled' after PE in Phase 5
    encryption: {
      services: {
        blob: { enabled: true, keyType: 'Account' }
        file: { enabled: true, keyType: 'Account' }
      }
      keySource: 'Microsoft.Storage'
      requireInfrastructureEncryption: true
    }
    networkAcls: {
      defaultAction: 'Allow'            // tighten in Phase 5
      bypass: 'AzureServices'
    }
  }
}

resource blob 'Microsoft.Storage/storageAccounts/blobServices@2024-01-01' = {
  parent: sa
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 30 }
    containerDeleteRetentionPolicy: { enabled: true, days: 30 }
    isVersioningEnabled: true
    changeFeed: { enabled: true, retentionInDays: 30 }
  }
}

var containers = [
  'inbound'      // raw uploaded docs
  'extracted'    // Content Understanding JSON + extracted images
  'translated'   // pass-1 / pass-2 translations
  'reviewed'     // post-judge artifacts
  'final'        // approved output docs
  'audit'        // full per-job audit bundle
]

@batchSize(1)
resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2024-01-01' = [ for c in containers: {
  parent: blob
  name: c
  properties: { publicAccess: 'None' }
}]

// Grant the workload MI: Storage Blob Data Contributor
var roleStorageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
resource mi_blobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sa.id, miPrincipalId, roleStorageBlobDataContributor)
  scope: sa
  properties: {
    principalId: miPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleStorageBlobDataContributor)
  }
}

output name string = sa.name
output id string = sa.id
output blobEndpoint string = sa.properties.primaryEndpoints.blob
