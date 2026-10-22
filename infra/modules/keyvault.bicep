// Key Vault with RBAC. Container apps read secrets as the workload identity
// through Key Vault references; nothing secret is in config or the image.
param name string
param location string
param tags object
param principalId string
@secure()
param secrets object

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 30
  }
}

resource secretItems 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = [for s in items(secrets): if (!empty(s.value)) {
  parent: vault
  name: s.key
  properties: { value: s.value }
}]

// Key Vault Secrets User for the workload identity.
resource reader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, principalId, '4633458b-17de-408a-b874-0445c86b69e6')
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}

output uri string = vault.properties.vaultUri
