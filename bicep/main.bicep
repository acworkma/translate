// =============================================================================
// Translate — Document translation workflow (hybrid: Azure AI Translator
// Document Translation as the format-preserving spine + LLM judge/revise).
// Scope: subscription. Creates rg-translate and dispatches workload module.
// =============================================================================
targetScope = 'subscription'

@description('Azure region. eastus2 has Content Understanding + AOAI + Language + xAI Grok.')
param location string = 'eastus2'

@description('Entra ID object ID of the user or group granted Key Vault Admin, AI Developer, Cosmos data.')
param adminPrincipalId string

@description('Optional tags merged onto the standard set.')
param extraTags object = {}

var baseTags = {
  workload: 'translate'
  dataClassification: 'PHI'
  managedBy: 'bicep'
}
var tags = union(baseTags, extraTags)

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-translate'
  location: location
  tags: tags
}

module workload 'workload.bicep' = {
  name: 'translate-workload'
  scope: rg
  params: {
    location: location
    tags: tags
    adminPrincipalId: adminPrincipalId
  }
}

output resourceGroupName string = rg.name
output foundryEndpoint string = workload.outputs.foundryEndpoint
output foundryProjectName string = workload.outputs.foundryProjectName
output storageAccountName string = workload.outputs.storageAccountName
output documentStorageBlobEndpoint string = workload.outputs.documentStorageBlobEndpoint
output keyVaultUri string = workload.outputs.keyVaultUri
output managedIdentityClientId string = workload.outputs.managedIdentityClientId
output appInsightsConnectionString string = workload.outputs.appInsightsConnectionString
output cosmosEndpoint string = workload.outputs.cosmosEndpoint
output cosmosDatabaseName string = workload.outputs.cosmosDatabaseName
output functionAppName string = workload.outputs.functionAppName
output functionAppHostname string = workload.outputs.functionAppHostname
output contentUnderstandingEndpoint string = workload.outputs.contentUnderstandingEndpoint
output contentUnderstandingAccountName string = workload.outputs.contentUnderstandingAccountName
