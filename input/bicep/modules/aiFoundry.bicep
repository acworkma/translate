// =============================================================================
// Azure AI Foundry — account (kind=AIServices) + project + model deployments
//
// This uses the unified Foundry resource model:
//   Microsoft.CognitiveServices/accounts (kind: AIServices)
//   Microsoft.CognitiveServices/accounts/projects
//
// Content Understanding, Language (Text Analytics for Health), Translator,
// Azure OpenAI, AND partner models sold directly by Azure (e.g. xAI Grok)
// are all consumed from this single AIServices endpoint.
//
// NOTE: If your tenant/region still requires the older Hub/Workspace pattern
// (Microsoft.MachineLearningServices/workspaces kind=Hub|Project), swap this
// module — the rest of the scaffold stays the same.
// =============================================================================
param accountName string
param projectName string
param location string
param tags object
param miPrincipalId string
param adminPrincipalId string

@description('Model deployments. `format` distinguishes Azure OpenAI ("OpenAI") from partner models ("xAI", "Mistral AI", "Meta", etc.).')
param modelDeployments array = [
  // Translator (Pass 1 + Pass 2)
  {
    name: 'gpt-4-1'
    format: 'OpenAI'
    model: 'gpt-4.1'
    version: '2025-04-14'
    sku: 'GlobalStandard'
    capacity: 50
  }
  // Utility / readability rewrite
  {
    name: 'gpt-4o-mini'
    format: 'OpenAI'
    model: 'gpt-4o-mini'
    version: '2024-07-18'
    sku: 'GlobalStandard'
    capacity: 100
  }
  // Judge — different vendor than translator to reduce self-preference bias
  // xAI Grok is sold directly by Azure (MaaS, pay-per-token).
  // Verify available models in your region:
  //   az cognitiveservices account list-models -n <foundry-account> -g <rg>
  {
    name: 'grok-3'
    format: 'xAI'
    model: 'grok-3'
    version: '1'
    sku: 'GlobalStandard'
    capacity: 1
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
    publicNetworkAccess: 'Enabled'      // flip after PE in Phase 5
    disableLocalAuth: false              // set true once everything is on Entra
    allowProjectManagement: true         // required to host /projects underneath
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
    description: 'Pediatric Discharge Translation workload'
  }
}

@batchSize(1)
resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = [ for m in modelDeployments: {
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

// Built-in role IDs
var roleCognitiveServicesUser            = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var roleCognitiveServicesOpenAIUser      = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var roleAzureAIDeveloper                 = '64702f94-c441-49e6-a78b-ef80e0188fee'

// Workload MI: data-plane access to Cognitive Services + AOAI
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

// Admin principal: project authoring in Foundry portal
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
