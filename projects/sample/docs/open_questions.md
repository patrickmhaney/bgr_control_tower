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

<!-- requirements:start - generated from requirements/ on every save; edit the answers, not this section -->

## Asked in the requirements

Answered "I don't know" in the Requirements tab, with who might know.

| Item | Question | Who might know |
|---|---|---|
| Process Procure to Pay (`P2P`) | Volume | Purchasing Manager |
| Dimension Product (`item`) | Roll-ups | Purchasing Manager |
| Measure Inventory Accuracy (`inventory_accuracy`) | Calculation | - |
| Measure Days Sales Outstanding (`days_sales_outstanding`) | Definition | - |

Flagged for follow-up.

| Item | Note |
|---|---|
| Process Procure to Pay (`P2P`) | - |
| Dimension Product (`item`) | - |
| Measure Inventory Accuracy (`inventory_accuracy`) | - |
| Measure Days Sales Outstanding (`days_sales_outstanding`) | - |
| Measure Cost Per Order (`cost_per_order`) | Which costs count? Freight only, or warehouse labour too. Ask the Finance Controller. |
| Measure Return Rate (`return_rate`) | - |

<!-- requirements:end -->
