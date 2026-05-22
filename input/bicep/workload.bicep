// =============================================================================
// Workload — all resources for one environment. Resource group scope.
// =============================================================================
param env string
param location string
param workload string
param tags object
param adminPrincipalId string

var suffix = uniqueString(resourceGroup().id, env)

var names = {
  managedIdentity: 'id-${workload}-${env}'
  logAnalytics:    'log-${workload}-${env}'
  appInsights:     'appi-${workload}-${env}'
  storage:         take(toLower(replace('st${workload}${env}${suffix}', '-', '')), 24)
  funcStorage:     take(toLower(replace('stfn${workload}${env}${suffix}', '-', '')), 24)
  keyVault:        take('kv-${workload}-${env}-${suffix}', 24)
  foundryAccount:  'aif-${workload}-${env}'
  foundryProject:  'proj-${workload}-${env}'
  cosmos:          take('cosmos-${workload}-${env}-${suffix}', 44)
  funcPlan:        'plan-${workload}-${env}'
  funcApp:         'func-${workload}-${env}-${suffix}'
}

module identity 'modules/identity.bicep' = {
  name: 'mod-identity'
  params: {
    name: names.managedIdentity
    location: location
    tags: tags
  }
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'mod-monitoring'
  params: {
    logAnalyticsName: names.logAnalytics
    appInsightsName: names.appInsights
    location: location
    tags: tags
  }
}

module storage 'modules/storage.bicep' = {
  name: 'mod-storage'
  params: {
    name: names.storage
    location: location
    tags: tags
    miPrincipalId: identity.outputs.principalId
  }
}

module keyVault 'modules/keyvault.bicep' = {
  name: 'mod-keyvault'
  params: {
    name: names.keyVault
    location: location
    tags: tags
    miPrincipalId: identity.outputs.principalId
    adminPrincipalId: adminPrincipalId
  }
}

module foundry 'modules/aiFoundry.bicep' = {
  name: 'mod-foundry'
  params: {
    accountName: names.foundryAccount
    projectName: names.foundryProject
    location: location
    tags: tags
    miPrincipalId: identity.outputs.principalId
    adminPrincipalId: adminPrincipalId
  }
}

// -------------------- Phase 3 additions --------------------
module cosmos 'modules/cosmos.bicep' = {
  name: 'mod-cosmos'
  params: {
    name: names.cosmos
    location: location
    tags: tags
    miPrincipalId: identity.outputs.principalId
    adminPrincipalId: adminPrincipalId
  }
}

module functionApp 'modules/functions.bicep' = {
  name: 'mod-functions'
  params: {
    functionAppName: names.funcApp
    planName: names.funcPlan
    funcStorageName: names.funcStorage
    location: location
    tags: tags
    miId: identity.outputs.id
    miPrincipalId: identity.outputs.principalId
    miClientId: identity.outputs.clientId
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    foundryEndpoint: foundry.outputs.endpoint
    cosmosEndpoint: cosmos.outputs.endpoint
    cosmosDatabaseName: cosmos.outputs.databaseName
    documentStorageBlobEndpoint: storage.outputs.blobEndpoint
  }
}

// -------------------- Outputs --------------------
output foundryEndpoint string = foundry.outputs.endpoint
output foundryProjectName string = foundry.outputs.projectName
output storageAccountName string = storage.outputs.name
output keyVaultUri string = keyVault.outputs.uri
output managedIdentityClientId string = identity.outputs.clientId
output appInsightsConnectionString string = monitoring.outputs.appInsightsConnectionString
output cosmosEndpoint string = cosmos.outputs.endpoint
output cosmosDatabaseName string = cosmos.outputs.databaseName
output functionAppName string = functionApp.outputs.functionAppName
output functionAppHostname string = functionApp.outputs.functionAppHostname
