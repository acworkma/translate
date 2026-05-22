// =============================================================================
// Azure AI Foundry — AIServices account + project + model deployments.
// Hosts: Content Understanding, Language (Text Analytics for Health),
// Translator (Document Translation), Azure OpenAI (gpt-4.1, gpt-4o-mini),
// and xAI Grok (judge).
// =============================================================================
param accountName string
param projectName string
param location string
param tags object
param miPrincipalId string
param adminPrincipalId string

@description('Model deployments. format=OpenAI for AOAI, format=xAI for Grok.')
param modelDeployments array = [
  {
    name: 'gpt-4-1'
    format: 'OpenAI'
    model: 'gpt-4.1'
    version: '2025-04-14'
    sku: 'GlobalStandard'
    capacity: 50
  }
  {
    name: 'gpt-4o-mini'
    format: 'OpenAI'
    model: 'gpt-4o-mini'
    version: '2024-07-18'
    sku: 'GlobalStandard'
    capacity: 100
  }
  // Judge — different vendor than translator to reduce self-preference bias.
  // grok-4-1-fast-reasoning verified available in eastus2 (GlobalStandard).
  {
    name: 'grok-4-1-fast-reasoning'
    format: 'xAI'
    model: 'grok-4-1-fast-reasoning'
    version: '1'
    sku: 'GlobalStandard'
    capacity: 20
  }
]

resource foundry 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: accountName
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
    allowProjectManagement: true
    networkAcls: { defaultAction: 'Allow', virtualNetworkRules: [], ipRules: [] }
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: foundry
  name: projectName
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: projectName
    description: 'Document Translation workload (hybrid Document Translation + LLM judge).'
  }
}

@batchSize(1)
resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = [for m in modelDeployments: {
  parent: foundry
  name: m.name
  sku: {
    name: m.sku
    capacity: m.capacity
  }
  properties: {
    model: {
      format: m.format
      name: m.model
      version: m.version
    }
    raiPolicyName: 'Microsoft.DefaultV2'
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}]

var roleCognitiveServicesUser       = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var roleCognitiveServicesOpenAIUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var roleAzureAIDeveloper            = '64702f94-c441-49e6-a78b-ef80e0188fee'

resource mi_cogUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, miPrincipalId, roleCognitiveServicesUser)
  scope: foundry
  properties: {
    principalId: miPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleCognitiveServicesUser)
  }
}

resource mi_openaiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, miPrincipalId, roleCognitiveServicesOpenAIUser)
  scope: foundry
  properties: {
    principalId: miPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleCognitiveServicesOpenAIUser)
  }
}

resource admin_aiDev 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, adminPrincipalId, roleAzureAIDeveloper)
  scope: foundry
  properties: {
    principalId: adminPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleAzureAIDeveloper)
  }
}

output endpoint string = foundry.properties.endpoint
output accountId string = foundry.id
output accountName string = foundry.name
output projectId string = project.id
output projectName string = project.name
output systemPrincipalId string = foundry.identity.principalId
