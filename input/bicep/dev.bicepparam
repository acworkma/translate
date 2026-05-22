using './main.bicep'

param env = 'dev'
param location = 'eastus2'
param workload = 'dischargemt'

// Replace with your Entra user or group object ID (run: az ad signed-in-user show --query id -o tsv)
param adminPrincipalId = '00000000-0000-0000-0000-000000000000'

param extraTags = {
  costCenter: 'HLS-CloudAI'
  project: 'Pediatric-Discharge-Translator'
}
