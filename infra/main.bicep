// The platform for one environment (dev, test or prod), in one resource group.
//
//   az deployment group create -g ct-dev -f infra/main.bicep -p infra/env/dev.bicepparam
//
// Every resource carries `env`, `component`, `stack` and `owner` tags. The
// component tag names the platform component a resource implements, which is
// what lets the cost export report cost by component (PLAN.md §7.10).

targetScope = 'resourceGroup'

@allowed(['dev', 'test', 'prod'])
param env string
param location string = resourceGroup().location
@description('Container image for both apps, e.g. ghcr.io/org/control-tower:sha')
param image string
param owner string = 'data-platform'
@description('Emails that receive budget and failure alerts.')
param alertEmails array
@description('Monthly budget for the resource group, in USD.')
param monthlyBudget int = 300
@secure()
param postgresAdminPassword string
@description('Incoming webhook (Teams/Slack) for failed pipeline runs. Optional.')
@secure()
param alertWebhook string = ''

var name = 'ct-${env}'
var baseTags = { env: env, stack: 'oss-baseline', owner: owner }

module identity 'modules/identity.bicep' = {
  name: 'identity'
  params: { name: name, location: location, tags: union(baseTags, { component: 'security' }) }
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: { name: name, location: location, tags: union(baseTags, { component: 'monitoring' }), alertEmails: alertEmails }
}

module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    accountName: replace('${name}lake', '-', '')
    location: location
    tags: union(baseTags, { component: 'raw_storage' })
    principalId: identity.outputs.principalId
  }
}

module keyvault 'modules/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    name: '${name}-kv'
    location: location
    tags: union(baseTags, { component: 'security' })
    principalId: identity.outputs.principalId
    secrets: {
      'postgres-password': postgresAdminPassword
      'alert-webhook': alertWebhook
    }
  }
}

module postgres 'modules/postgres.bicep' = {
  name: 'postgres'
  params: {
    name: '${name}-pg'
    location: location
    tags: union(baseTags, { component: 'downstream_apps' })
    adminPassword: postgresAdminPassword
  }
}

module apps 'modules/containerapps.bicep' = {
  name: 'apps'
  params: {
    name: name
    env: env
    location: location
    baseTags: baseTags
    image: image
    identityId: identity.outputs.id
    identityClientId: identity.outputs.clientId
    logAnalyticsCustomerId: monitoring.outputs.customerId
    logAnalyticsKey: monitoring.outputs.sharedKey
    storageAccount: storage.outputs.accountName
    postgresHost: postgres.outputs.host
    keyVaultUri: keyvault.outputs.uri
    actionGroupId: monitoring.outputs.actionGroupId
  }
}

module catalog 'modules/staticweb.bicep' = {
  name: 'catalog'
  params: { name: '${name}-catalog', tags: union(baseTags, { component: 'governance' }) }
}

module budget 'modules/budget.bicep' = {
  name: 'budget'
  params: { name: '${name}-budget', amount: monthlyBudget, contactEmails: alertEmails }
}

module costExport 'modules/costexport.bicep' = {
  name: 'cost-export'
  params: { name: '${name}-focus-daily', storageAccountId: storage.outputs.id }
}

output dataServiceUrl string = apps.outputs.dataServiceUrl
output dagsterUrl string = apps.outputs.dagsterUrl
output storageAccount string = storage.outputs.accountName
output catalogUrl string = catalog.outputs.url
