using './main.bicep'

param location = 'eastus2'

// Resolved via: az ad signed-in-user show --query id -o tsv
param adminPrincipalId = 'fdb5277a-b882-49f6-998f-9242eeba6034'

param extraTags = {
  costCenter: 'translate'
  project: 'document-translation'
}
