// =============================================================================
// Cosmos DB (SQL API, serverless) for job state, glossary, and audit
// =============================================================================
param name string
param location string
param tags object
param miPrincipalId string
param adminPrincipalId string

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: name
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  identity: { type: 'SystemAssigned' }
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      { locationName: location, failoverPriority: 0, isZoneRedundant: false }
    ]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    capabilities: [ { name: 'EnableServerless' } ]
    publicNetworkAccess: 'Enabled'   // flip after PE in Phase 5
    disableLocalAuth: true            // Entra-only — keys cannot be used
    minimalTlsVersion: 'Tls12'
    enableAutomaticFailover: false
    networkAclBypass: 'AzureServices'
  }
}

resource db 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: cosmos
  name: 'dischargemt'
  properties: {
    resource: { id: 'dischargemt' }
  }
}

var containers = [
  // Per-job state machine: status, scores, decisions, references to blob artifacts
  { name: 'jobs',     partitionKey: '/jobId',    ttl: -1 }
  // Approved terminology by language — pinned translations + DNT
  { name: 'glossary', partitionKey: '/language', ttl: -1 }
  // Per-job audit trail (one document per pipeline step)
  { name: 'audit',    partitionKey: '/jobId',    ttl: 7776000 }  // 90 days
  // Reviewer queue + decisions
  { name: 'reviews',  partitionKey: '/jobId',    ttl: -1 }
]

@batchSize(1)
resource container 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = [ for c in containers: {
  parent: db
  name: c.name
  properties: {
    resource: {
      id: c.name
      partitionKey: { paths: [ c.partitionKey ], kind: 'Hash' }
      defaultTtl: c.ttl
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [ { path: '/*' } ]
        excludedPaths: [ { path: '/"_etag"/?' } ]
      }
    }
  }
}]

// Cosmos SQL "Built-in Data Contributor" — data-plane role (NOT an Azure RBAC role)
// This GUID is the same in every Cosmos account; the assignment scope makes it specific.
var cosmosBuiltInDataContributorId = '00000000-0000-0000-0000-000000000002'

resource sqlRoleMI 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmos
  name: guid(cosmos.id, miPrincipalId, 'data-contributor')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosBuiltInDataContributorId}'
    principalId: miPrincipalId
    scope: cosmos.id
  }
}

resource sqlRoleAdmin 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmos
  name: guid(cosmos.id, adminPrincipalId, 'data-contributor')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosBuiltInDataContributorId}'
    principalId: adminPrincipalId
    scope: cosmos.id
  }
}

output endpoint string = cosmos.properties.documentEndpoint
output name string = cosmos.name
output id string = cosmos.id
output databaseName string = db.name
