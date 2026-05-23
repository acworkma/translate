// Container Registry for the demo app. Separated from the ACA module so the
// registry can exist before the image build, and the ACA module can reference it.
param name string
param location string
param tags object

resource acr 'Microsoft.ContainerRegistry/registries@2024-11-01-preview' = {
  name: name
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

output id string = acr.id
output name string = acr.name
output loginServer string = acr.properties.loginServer
