using '../main.bicep'

param env = 'dev'
param image = readEnvironmentVariable('CT_IMAGE', 'ghcr.io/your-org/control-tower:latest')
param alertEmails = [readEnvironmentVariable('CT_ALERT_EMAIL', 'data-platform@example.com')]
param monthlyBudget = 300
param postgresAdminPassword = readEnvironmentVariable('CT_POSTGRES_PASSWORD')
param alertWebhook = readEnvironmentVariable('CT_ALERT_WEBHOOK', '')
