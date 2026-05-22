// User-assigned managed identity used by all workload compute (Functions, Container Apps, etc.)
param name string
param location string
param tags object

resource mi 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: name
  location: location
  tags: tags
}

output id string = mi.id
output principalId string = mi.properties.principalId
output clientId string = mi.properties.clientId
