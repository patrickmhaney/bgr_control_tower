// A monthly budget on the resource group, alerting at 50, 80 and 100%.
param name string
param amount int
param contactEmails array
param startDate string = '${utcNow('yyyy-MM')}-01'

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: name
  properties: {
    category: 'Cost'
    amount: amount
    timeGrain: 'Monthly'
    timePeriod: { startDate: startDate }
    notifications: {
      at50: { enabled: true, operator: 'GreaterThan', threshold: 50, contactEmails: contactEmails }
      at80: { enabled: true, operator: 'GreaterThan', threshold: 80, contactEmails: contactEmails }
      at100: { enabled: true, operator: 'GreaterThan', threshold: 100, contactEmails: contactEmails }
    }
  }
}
