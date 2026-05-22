// Key Vault with RBAC auth, soft-delete + purge protection
param name string
param location string
param tags object
param miPrincipalId string
param adminPrincipalId string

resource kv 'Microsoft.KeyVault/vaults@2024-04-01-preview' = {
  name: name
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { name: 'standard', family: 'A' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: true
    publicNetworkAccess: 'Enabled'   // flip to 'Disabled' after PE in Phase 5
    networkAcls: { defaultAction: 'Allow', bypass: 'AzureServices' }
  }
}

// Built-in role IDs
var roleKvSecretsUser    = '4633458b-17de-408a-b874-0445c86b69e6'
var roleKvAdministrator  = '00482a5a-887f-4fb3-b363-3b7fe8e74483'

resource mi_secretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, miPrincipalId, roleKvSecretsUser)
  scope: kv
  properties: {
    principalId: miPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleKvSecretsUser)
  }
}

resource admin_kvAdmin 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, adminPrincipalId, roleKvAdministrator)
  scope: kv
  properties: {
    principalId: adminPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleKvAdministrator)
  }
}

output name string = kv.name
output id string = kv.id
output uri string = kv.properties.vaultUri
