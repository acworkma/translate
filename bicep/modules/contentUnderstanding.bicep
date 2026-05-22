// =============================================================================
// Content Understanding — dedicated AIServices account in a CU-supported region.
// CU preview is not currently in eastus2 (the workload region), so we deploy a
// single-purpose Cognitive Services account in `location` and grant the workload
// UAMI Cognitive Services User.
// =============================================================================

@description('Region that supports Content Understanding preview (swedencentral, westus, or australiaeast).')
param location string

@description('CAF-style account name, e.g. cog-translate-cu-swc.')
param name string

@description('Workload UAMI principal id, granted Cognitive Services User on this account.')
param uamiPrincipalId string

@description('Admin principal id, granted Azure AI Developer on this account.')
param adminPrincipalId string

@description('Tags.')
param tags object = {}

resource cu 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: name
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: name
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
  }
}

var roleCognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var roleAzureAIDeveloper      = '64702f94-c441-49e6-a78b-ef80e0188fee'

resource mi_cogUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: cu
  name: guid(cu.id, uamiPrincipalId, roleCognitiveServicesUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleCognitiveServicesUser)
    principalId: uamiPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource admin_aiDev 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: cu
  name: guid(cu.id, adminPrincipalId, roleAzureAIDeveloper)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleAzureAIDeveloper)
    principalId: adminPrincipalId
    principalType: 'User'
  }
}

output endpoint string = cu.properties.endpoint
output name string = cu.name
output id string = cu.id
