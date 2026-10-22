// Static Web App (free tier) hosting dbt docs and the metric catalog, behind
// Entra sign-in. CD uploads the built site.
param name string
param tags object

resource site 'Microsoft.Web/staticSites@2023-12-01' = {
  name: name
  location: 'eastus2'
  tags: tags
  sku: { name: 'Free', tier: 'Free' }
  properties: {}
}

output url string = 'https://${site.properties.defaultHostname}'
