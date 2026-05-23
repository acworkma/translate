// =============================================================================
// Demo UI: ACA Environment + Container App. Consumes an existing ACR.
// =============================================================================
@description('Existing Container Registry name.')
param acrName string

@description('Container Apps environment name.')
param envName string

@description('Container App name.')
param appName string

@description('User-assigned managed identity name for the demo app.')
param uamiName string

@description('Location for all resources.')
param location string

param tags object

@description('Log Analytics workspace resource ID for the ACA environment.')
param logAnalyticsWorkspaceId string

@description('Customer ID of the Log Analytics workspace.')
param logAnalyticsCustomerId string

@description('Function App hostname (e.g. func-translate-topmsk.azurewebsites.net).')
param functionHost string

@description('Storage account name hosting the inbound/translated/final containers.')
param storageAccountName string

@description('Key Vault URI hosting the function key secret.')
param keyVaultUri string

@description('Name of the function-key secret in Key Vault.')
param functionKeySecretName string

@description('Resource ID of the Key Vault (for RBAC scoping).')
param keyVaultId string

@description('Resource ID of the storage account (for RBAC scoping).')
param storageAccountId string

@description('Supported language codes (csv).')
param supportedLanguages string = 'es,zh-Hans,vi,ar,ru'

@description('Demo password for the UI gate.')
@secure()
param demoPassword string

@description('Session signing secret.')
@secure()
param sessionSecret string

@description('Container image tag to deploy. The image must be pushed to the ACR before this template is applied.')
param imageTag string = 'latest'

// ---------- UAMI ----------
resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: uamiName
  location: location
  tags: tags
}

// ---------- existing ACR ----------
resource acr 'Microsoft.ContainerRegistry/registries@2024-11-01-preview' existing = {
  name: acrName
}

// AcrPull for the container app UAMI
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
resource acrPullAssign 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, uami.id, acrPullRoleId)
  scope: acr
  properties: {
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
  }
}

// Storage Blob Data Contributor on the document storage account
resource sa 'Microsoft.Storage/storageAccounts@2024-01-01' existing = {
  name: storageAccountName
}
var blobContribRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
resource blobAssign 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccountId, uami.id, blobContribRoleId)
  scope: sa
  properties: {
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobContribRoleId)
  }
}

// Key Vault Secrets User
resource kv 'Microsoft.KeyVault/vaults@2024-04-01-preview' existing = {
  name: last(split(keyVaultId, '/'))
}
var kvSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
resource kvAssign 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVaultId, uami.id, kvSecretsUserRoleId)
  scope: kv
  properties: {
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsUserRoleId)
  }
}

// ---------- ACA Environment ----------
resource env 'Microsoft.App/managedEnvironments@2024-10-02-preview' = {
  name: envName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsCustomerId
        sharedKey: listKeys(logAnalyticsWorkspaceId, '2023-09-01').primarySharedKey
      }
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
  }
}

// ---------- Container App ----------
var functionKeySecretUri = '${keyVaultUri}secrets/${functionKeySecretName}'

resource app 'Microsoft.App/containerApps@2024-10-02-preview' = {
  name: appName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uami.id}': {}
    }
  }
  properties: {
    environmentId: env.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: uami.id
        }
      ]
      secrets: [
        {
          name: 'demo-password'
          value: demoPassword
        }
        {
          name: 'session-secret'
          value: sessionSecret
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'demo'
          image: '${acr.properties.loginServer}/translate-demo:${imageTag}'
          resources: {
            cpu: json('0.5')
            memory: '1.0Gi'
          }
          env: [
            { name: 'AZURE_CLIENT_ID', value: uami.properties.clientId }
            { name: 'FUNCTION_HOST', value: 'https://${functionHost}' }
            { name: 'FUNCTION_KEY_SECRET_URI', value: functionKeySecretUri }
            { name: 'STORAGE_ACCOUNT_NAME', value: storageAccountName }
            { name: 'SUPPORTED_LANGUAGES', value: supportedLanguages }
            { name: 'DEMO_PASSWORD', secretRef: 'demo-password' }
            { name: 'SESSION_SECRET', secretRef: 'session-secret' }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/health', port: 8000 }
              initialDelaySeconds: 15
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: { path: '/health', port: 8000 }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
        rules: [
          {
            name: 'http'
            http: {
              metadata: {
                concurrentRequests: '20'
              }
            }
          }
        ]
      }
    }
  }
  dependsOn: [
    acrPullAssign
    kvAssign
    blobAssign
  ]
}

output appFqdn string = app.properties.configuration.ingress.fqdn
output appName string = app.name
output uamiPrincipalId string = uami.properties.principalId
output uamiClientId string = uami.properties.clientId
