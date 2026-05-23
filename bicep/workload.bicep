// =============================================================================
// Workload (resource group scope) — composes every module with CAF names.
// =============================================================================
param location string
param tags object
param adminPrincipalId string

@description('Region for the Content Understanding account (CU preview not yet in eastus2). Default westus.')
param cuLocation string = 'westus'

@description('Deploy the demo container app + ACA environment (set false to only create the ACR).')
param deployDemoApp bool = false

@description('Container image tag for the demo app (must be pushed before deployDemoApp=true).')
param demoImageTag string = 'latest'

@description('Demo UI password.')
@secure()
param demoPassword string = 'fr24'

@description('Demo UI session signing secret.')
@secure()
param demoSessionSecret string = newGuid()

@description('Name of the Key Vault secret holding the function key.')
param functionKeySecretName string = 'function-key'

// Shared 6-char uniqueness suffix for globally-unique names.
var suffix = take(uniqueString(resourceGroup().id), 6)

var names = {
  managedIdentity: 'id-translate-eus2'
  logAnalytics:    'log-translate-eus2'
  appInsights:     'appi-translate-eus2'
  storage:         take(toLower(replace('sttranslate${suffix}', '-', '')), 24)
  funcStorage:     take(toLower(replace('stfunctranslate${suffix}', '-', '')), 24)
  keyVault:        take('kv-translate-${suffix}', 24)
  foundryAccount:  'aif-translate-eus2'
  foundryProject:  'proj-translate-eus2'
  cosmos:          take('cosmos-translate-${suffix}', 44)
  funcPlan:        'asp-translate-eus2'
  funcApp:         'func-translate-${suffix}'
  contentUnderstanding: 'cog-translate-cu-wus'
  demoAcr:        take(toLower(replace('acrtranslate${suffix}', '-', '')), 50)
  demoEnv:        'cae-translate-eus2'
  demoApp:        'ca-translate-demo'
  demoUami:       'id-translate-demo-eus2'
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

// Storage created AFTER foundry so we can grant the Foundry account's
// system-assigned MI Blob Data Contributor on the document storage account
// (required so Document Translation can read source / write target via MI).
module storage 'modules/storage.bicep' = {
  name: 'mod-storage'
  params: {
    name: names.storage
    location: location
    tags: tags
    miPrincipalId: identity.outputs.principalId
    foundryPrincipalId: foundry.outputs.systemPrincipalId
  }
}

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

module contentUnderstanding 'modules/contentUnderstanding.bicep' = {
  name: 'mod-cu'
  params: {
    name: names.contentUnderstanding
    location: cuLocation
    tags: tags
    uamiPrincipalId: identity.outputs.principalId
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
    documentStorageAccountName: storage.outputs.name
    documentStorageBlobEndpoint: storage.outputs.blobEndpoint
    contentUnderstandingEndpoint: contentUnderstanding.outputs.endpoint
  }
}

module demoAcr 'modules/demoAcr.bicep' = {
  name: 'mod-demo-acr'
  params: {
    name: names.demoAcr
    location: location
    tags: tags
  }
}

module demoApp 'modules/demoApp.bicep' = if (deployDemoApp) {
  name: 'mod-demo-app'
  params: {
    acrName: demoAcr.outputs.name
    envName: names.demoEnv
    appName: names.demoApp
    uamiName: names.demoUami
    location: location
    tags: tags
    logAnalyticsWorkspaceId: monitoring.outputs.logAnalyticsId
    logAnalyticsCustomerId: monitoring.outputs.logAnalyticsCustomerId
    functionHost: functionApp.outputs.functionAppHostname
    storageAccountName: storage.outputs.name
    storageAccountId: storage.outputs.id
    keyVaultUri: keyVault.outputs.uri
    keyVaultId: keyVault.outputs.id
    functionKeySecretName: functionKeySecretName
    demoPassword: demoPassword
    sessionSecret: demoSessionSecret
    imageTag: demoImageTag
  }
}

output foundryEndpoint string = foundry.outputs.endpoint
output foundryProjectName string = foundry.outputs.projectName
output storageAccountName string = storage.outputs.name
output documentStorageBlobEndpoint string = storage.outputs.blobEndpoint
output keyVaultUri string = keyVault.outputs.uri
output keyVaultName string = keyVault.outputs.name
output managedIdentityClientId string = identity.outputs.clientId
output appInsightsConnectionString string = monitoring.outputs.appInsightsConnectionString
output cosmosEndpoint string = cosmos.outputs.endpoint
output cosmosDatabaseName string = cosmos.outputs.databaseName
output functionAppName string = functionApp.outputs.functionAppName
output functionAppHostname string = functionApp.outputs.functionAppHostname
output contentUnderstandingEndpoint string = contentUnderstanding.outputs.endpoint
output contentUnderstandingAccountName string = contentUnderstanding.outputs.name
output demoAcrLoginServer string = demoAcr.outputs.loginServer
output demoAcrName string = demoAcr.outputs.name
output demoAppFqdn string = deployDemoApp ? demoApp!.outputs.appFqdn : ''