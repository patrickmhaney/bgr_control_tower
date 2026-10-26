# Open questions

What the Sample Project's numbers assume, and what reversing each costs. The
requirements live in the requirements tool's Sample Project workspace; this
pack is compiled from it (contract C8), so most answers change there, not here.

| # | Question | Assumed | Where it lives | Reversing it |
|---|---|---|---|---|
| 1 | On-Time Delivery: per shipment or per delivery line? | Per delivery line, against the requested date | `fct_delivery_line` | Re-grain the fact; numbers move |
| 2 | Inventory Accuracy: by item or by location? | By counted position (item x site x location), exact match | `fct_inventory_count_line`, var `inventory_accuracy_tolerance_pct` | A var for the tolerance; a model change for the grain |
| 3 | Return Rate: which source systems? | Credit value of returns over invoiced value, ERP only | `fct_sales_order_line` | An answer in the requirements tool |
| 4 | Three-Way Match Rate: what tolerance? | Exact quantity, 2% price | vars `match_qty_tolerance_pct`, `match_price_tolerance_pct` | A var |
| 5 | Days Sales Outstanding: the agreed formula needs month-end receivable balances | Not computed (placeholder) | `backlog.yml` | A month-end AR snapshot in gold |
| 6 | Cost Per Order: which costs count? | Not computed (placeholder) | `backlog.yml` | An answer in the requirements tool, then a definition |
| 7 | Supplier On-Time Rate: per receipt promised date | Not computed (placeholder) | `backlog.yml` | The promised date on each PO line receipt |
| 8 | Cost Per Shipment: late carrier invoices | Invoiced shipments only, so recent months restate as invoices arrive | `fct_shipment` | A caveat, or an accrual for uninvoiced shipments |
| 9 | Payroll | No simulator in the architecture yet | `project.yml` | A payroll simulator and staging adapter |
| 10 | Fiscal calendar | Fiscal = calendar | var `fiscal_year_start_month` | A var |
