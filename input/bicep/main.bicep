// =============================================================================
// Pediatric Discharge Translator — Phase 0/1/3 foundations
// Scope: subscription. Creates RG and deploys workload.
// =============================================================================
targetScope = 'subscription'

@description('Environment short name')
@allowed([ 'dev', 'test', 'prod' ])
param env string = 'dev'

@description('Azure region. Use a region with Content Understanding + AOAI + Language + xAI Grok (e.g., eastus2, westus3).')
param location string = 'eastus2'

@description('Workload prefix used for naming.')
param workload string = 'dischargemt'

@description('Entra ID object ID of the user or group to grant initial admin RBAC (Key Vault Admin, AI Developer, Cosmos data).')
param adminPrincipalId string

@description('Optional tags merged onto the standard set.')
param extraTags object = {}

var baseTags = {
  workload: workload
  env: env
  owner: 'hls-cloud-ai'
  dataClassification: 'PHI'
  managedBy: 'bicep'
}
var tags = union(baseTags, extraTags)

var rgName = 'rg-${workload}-${env}'

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: rgName
  location: location
  tags: tags
}

module workload_ './workload.bicep' = {
  name: 'workload-${env}'
  scope: rg
  params: {
    env: env
    location: location
    workload: workload
    tags: tags
    adminPrincipalId: adminPrincipalId
  }
}

output resourceGroupName string = rg.name
output foundryEndpoint string = workload_.outputs.foundryEndpoint
output foundryProjectName string = workload_.outputs.foundryProjectName
output storageAccountName string = workload_.outputs.storageAccountName
output keyVaultUri string = workload_.outputs.keyVaultUri
output managedIdentityClientId string = workload_.outputs.managedIdentityClientId
output appInsightsConnectionString string = workload_.outputs.appInsightsConnectionString
output cosmosEndpoint string = workload_.outputs.cosmosEndpoint
output cosmosDatabaseName string = workload_.outputs.cosmosDatabaseName
output functionAppName string = workload_.outputs.functionAppName
output functionAppHostname string = workload_.outputs.functionAppHostname
