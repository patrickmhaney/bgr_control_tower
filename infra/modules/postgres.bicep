// Postgres on the burstable tier: Dagster's run storage and the serving
// database apps read (contract C7).
param name string
param location string
param tags object
@secure()
param adminPassword string

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' = {
  name: name
  location: location
  tags: tags
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '16'
    administratorLogin: 'ctadmin'
    administratorLoginPassword: adminPassword
    storage: { storageSizeGB: 32 }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
  }
}

// POC: Azure services may connect. Production replaces this with private
// endpoints and VNet integration (PLAN.md §7.11).
resource allowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-06-01-preview' = {
  parent: server
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}

resource databases 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-06-01-preview' = [for db in ['dagster', 'serving']: {
  parent: server
  name: db
}]

output host string = server.properties.fullyQualifiedDomainName
