// The daily Cost Management export, in FOCUS format, into the costs
// container. The platform ingests it like any other source (azure_cost) into
// gold.fct_cloud_cost, so cost by component is a dashboard page.
param name string
param storageAccountId string
param startDate string = utcNow('yyyy-MM-ddT00:00:00Z')

resource export 'Microsoft.CostManagement/exports@2023-07-01-preview' = {
  name: name
  properties: {
    schedule: {
      status: 'Active'
      recurrence: 'Daily'
      recurrencePeriod: { from: startDate, to: '2030-12-31T00:00:00Z' }
    }
    format: 'Csv'
    deliveryInfo: {
      destination: { resourceId: storageAccountId, container: 'costs', rootFolderPath: 'focus' }
    }
    definition: {
      type: 'FocusCost'
      timeframe: 'MonthToDate'
      dataSet: { granularity: 'Daily' }
    }
  }
}
