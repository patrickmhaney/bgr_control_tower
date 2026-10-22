// Two container apps from one image: Dagster (webserver + daemon, the only
// writer of the warehouse file) and the data service (REST + MCP, read-only).
// The data service sits behind Container Apps authentication (Entra ID),
// configured after deployment with `az containerapp auth microsoft update`.
param name string
param env string
param location string
param baseTags object
param image string
param identityId string
param identityClientId string
param logAnalyticsCustomerId string
@secure()
param logAnalyticsKey string
param storageAccount string
param postgresHost string
param keyVaultUri string
param actionGroupId string

var common = [
  { name: 'PLATFORM_ENV', value: env }
  { name: 'CT_STORAGE_ACCOUNT', value: storageAccount }
  { name: 'AZURE_CLIENT_ID', value: identityClientId }
  { name: 'CT_SERVING_URL', value: 'postgresql://ctadmin@${postgresHost}:5432/serving?sslmode=require' }
  { name: 'CT_SERVING_PASSWORD', secretRef: 'postgres-password' }
]
var secrets = [
  { name: 'postgres-password', keyVaultUrl: '${keyVaultUri}secrets/postgres-password', identity: identityId }
  { name: 'alert-webhook', keyVaultUrl: '${keyVaultUri}secrets/alert-webhook', identity: identityId }
]

resource managedEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${name}-env'
  location: location
  tags: union(baseTags, { component: 'compute' })
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: { customerId: logAnalyticsCustomerId, sharedKey: logAnalyticsKey }
    }
  }
}

resource dagster 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${name}-dagster'
  location: location
  tags: union(baseTags, { component: 'orchestration' })
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identityId}': {} } }
  properties: {
    managedEnvironmentId: managedEnv.id
    configuration: {
      secrets: secrets
      ingress: { external: true, targetPort: 3000 }
    }
    template: {
      containers: [{
        name: 'dagster'
        image: image
        command: ['/app/orchestration/entrypoint.sh']
        resources: { cpu: json('2.0'), memory: '4Gi' }
        env: concat(common, [
          { name: 'DAGSTER_PG_HOST', value: postgresHost }
          { name: 'DAGSTER_PG_USER', value: 'ctadmin' }
          { name: 'DAGSTER_PG_PASSWORD', secretRef: 'postgres-password' }
          { name: 'CT_ALERT_WEBHOOK', secretRef: 'alert-webhook' }
        ])
      }]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

resource dataService 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${name}-data-service'
  location: location
  tags: union(baseTags, { component: 'downstream_apps' })
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identityId}': {} } }
  properties: {
    managedEnvironmentId: managedEnv.id
    configuration: {
      secrets: secrets
      ingress: { external: true, targetPort: 8000 }
    }
    template: {
      containers: [{
        name: 'data-service'
        image: image
        resources: { cpu: json('1.0'), memory: '2Gi' }
        env: concat(common, [
          { name: 'CT_ALLOWED_HOSTS', value: '${name}-data-service.${managedEnv.properties.defaultDomain}' }
        ])
      }]
      scale: { minReplicas: 0, maxReplicas: 2 }
    }
  }
}

// Alert when a container restarts repeatedly - a crash loop in either app.
resource restarts 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: '${name}-restarts'
  location: 'global'
  tags: union(baseTags, { component: 'monitoring' })
  properties: {
    severity: 2
    enabled: true
    scopes: [dagster.id, dataService.id]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    targetResourceType: 'Microsoft.App/containerApps'
    targetResourceRegion: location
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.MultipleResourceMultipleMetricCriteria'
      allOf: [{
        criterionType: 'StaticThresholdCriterion'
        name: 'restarts'
        metricName: 'RestartCount'
        operator: 'GreaterThan'
        threshold: 3
        timeAggregation: 'Total'
      }]
    }
    actions: [{ actionGroupId: actionGroupId }]
  }
}

output dataServiceUrl string = 'https://${dataService.properties.configuration.ingress.fqdn}'
output dagsterUrl string = 'https://${dagster.properties.configuration.ingress.fqdn}'
