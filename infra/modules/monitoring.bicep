// Log Analytics (container logs, the audit log of AI queries), Application
// Insights, and the action group every alert notifies.
param name string
param location string
param tags object
param alertEmails array

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${name}-logs'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${name}-insights'
  location: location
  tags: tags
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: logs.id }
}

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: '${name}-alerts'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: 'ct-alerts'
    enabled: true
    emailReceivers: [for (email, i) in alertEmails: {
      name: 'email-${i}'
      emailAddress: email
      useCommonAlertSchema: true
    }]
  }
}

output customerId string = logs.properties.customerId
#disable-next-line outputs-should-not-contain-secrets
output sharedKey string = logs.listKeys().primarySharedKey
output actionGroupId string = actionGroup.id
output workspaceId string = logs.id
