# Open questions

What the data and the design could not answer. **None blocks the build**: each
has a documented assumption, encoded as a var, a metric's status, a seed or a
decision, so the answer changes configuration rather than models. The
platform-level questions (Q-A to Q-J) are also in [PLAN.md §12](../PLAN.md).

## Business definitions

| # | Question | Assumed | Encoded as | Cost to reverse |
|---|---|---|---|---|
| 1 | On-Time Delivery: against which promise - the customer's requested date, or a confirmed ship date? | Requested date | the metric's numerator (`is_on_time` on `fct_delivery_line`) | One fact column + one definition |
| 2 | DSO: a balance-based DSO, or the days-to-pay proxy? | Days-to-pay proxy, published beside Unsettled Invoice Rate | `status: provisional` | A new fact (AR balances) + one definition |
| 3 | Cost Per Order: which cost pool? | Not computable - no freight source | `backlog.yml` (blocked) | A source |
| 4 | Fiscal calendar | Fiscal = calendar | `var: fiscal_year_start_month` | One var; fiscal grains follow |
| 7 | Customer survivorship between X3 and HubSpot | X3 wins financial, HubSpot firmographic attributes | `dim_customer` | One model |
| 8 | Metric ownership | Unassigned; roles proposed | `owner: TBD`, `owner_proposed` | Metadata |
| 10 | Currency policy | USD at the GL-derived monthly rate | `var: reporting_currency`, `int_fx_rate` | One model, once a rate feed exists |
| 11 | As-was attribution (e.g. revenue by the rep at the time)? | As-is today | CDC keeps every before-image in bronze, so as-was can be built later at no loss | One Type 2 model when needed |
| 14 | Three-way match tolerance | Exact quantity, 2% price | `var: match_*_tolerance_pct` | Two vars |
| 15 | Inventory accuracy tolerance | Exact match, by position | `var: inventory_accuracy_tolerance_pct` | One var |
| 16 | Return Rate denominator | Invoiced value | the metric's denominator | One definition |
| 17 | Return Rate date basis | Order date | the fact's time dimension | One definition |
| 18 | Order Fill Rate: do open orders count as unfilled? | Yes, cancelled orders excluded | the metric's filter | One filter |
| 19 | Forecast Accuracy: which measure? | 1 − WMAPE | a derived metric | One definition |
| 20 | Win Rate, Pipeline Value, Sales Cycle Days: confirmed definitions? | Working definitions | `status: provisional` | One definition each |
| 21 | Supplier On-Time Receipt: do partial receipts count? | Undefined | `backlog.yml` (placeholder) | One definition |

Questions 5, 6, 9, 12 and 13 from the v1 prequel are closed: the semantic
layer tool is MetricFlow (decision D1), the Power BI topology recommendation
stands (one shared model), and the remaining three concerned a source no
longer in scope.

## Platform and client

| # | Question | Affects |
|---|---|---|
| Q-A | What are the departments, and does "departmental activity" mean the person who did the work (decision D7)? | `seeds/department.csv`, `function_profile_department.csv`, `hubspot_team_department.csv` |
| Q-B | Which processes and departments own which metrics? The process acronyms are unexpanded. | The two dashboard seeds |
| Q-C | Where does X3 run, which SQL Server edition, and can CDC (or Change Tracking) be enabled? | The X3 extraction path and the network design |
| Q-D | What Power BI licensing exists (Pro, PPU, Fabric capacity)? | How the model deploys; whether Direct Lake is an option |
| Q-E | Which master data domains must the chosen MDM cover, and must it sync back into X3 and HubSpot? | The scope of contract C3 |
| Q-F | Is there a Windows machine for Power BI Desktop? | Opening the generated model, building the reports |
| Q-G | Which Azure subscription, region and naming convention, and who approves spend? | Deploying `infra/` |
| Q-H | GitHub or Azure DevOps? | `.github/workflows/` |
| Q-I | The project's final name, and whether the repo will be shared beyond the client (this branch's early history names the client) | Starting a fresh repository from the clean tree |
| Q-J | Do client-derived details that do not name the client (process acronyms, site cities) need to go too? | Seeds and the generator |

## Table names to verify

The X3 counting, returns, receipt, supplier invoice, delivery and user tables
(`STOCOUNT`/`STOCOUNTD`, `SRETURN`/`SRETURND`, `PRECEIPT`/`PRECEIPTD`,
`PINVOICE`/`PINVOICED`, `SDELIVERY`/`SDELIVERYD`, `AUTILIS`) follow X3
conventions but must be checked against the client's folder before anything
points at a real database. Staging absorbs a rename.

<!-- requirements:start - generated from requirements/ on every save; edit the answers, not this section -->

## Asked in the requirements

Answered "I don't know" in the Requirements tab, with who might know.

| Item | Question | Who might know |
|---|---|---|
| Process Sales pipeline (`P2C`) | Purpose | - |
| Process Sales pipeline (`P2C`) | Start and end | - |
| Process Sales pipeline (`P2C`) | Steps | - |
| Process Sales pipeline (`P2C`) | What it records | - |
| Process Sales pipeline (`P2C`) | Volume | - |
| Process Sales pipeline (`P2C`) | Decisions it supports | - |
| Process Sales pipeline (`P2C`) | Pain points | - |
| Process Sales pipeline (`P2C`) | Owner | - |
| Process Sales pipeline (`P2C`) | Priority | - |
| Process Order to Cash (`O2C`) | Purpose | - |
| Process Order to Cash (`O2C`) | Start and end | - |
| Process Order to Cash (`O2C`) | Steps | - |
| Process Order to Cash (`O2C`) | What it records | - |
| Process Order to Cash (`O2C`) | Volume | - |
| Process Order to Cash (`O2C`) | Decisions it supports | - |
| Process Order to Cash (`O2C`) | Pain points | - |
| Process Order to Cash (`O2C`) | Owner | - |
| Process Order to Cash (`O2C`) | Priority | - |
| Process Source to Pay (`S2P`) | Purpose | - |
| Process Source to Pay (`S2P`) | Start and end | - |
| Process Source to Pay (`S2P`) | Steps | - |
| Process Source to Pay (`S2P`) | What it records | - |
| Process Source to Pay (`S2P`) | Volume | - |
| Process Source to Pay (`S2P`) | Decisions it supports | - |
| Process Source to Pay (`S2P`) | Pain points | - |
| Process Source to Pay (`S2P`) | Owner | - |
| Process Source to Pay (`S2P`) | Priority | - |
| Process Forecast to Plan (`F2P`) | Purpose | - |
| Process Forecast to Plan (`F2P`) | Start and end | - |
| Process Forecast to Plan (`F2P`) | Steps | - |
| Process Forecast to Plan (`F2P`) | What it records | - |
| Process Forecast to Plan (`F2P`) | Volume | - |
| Process Forecast to Plan (`F2P`) | Decisions it supports | - |
| Process Forecast to Plan (`F2P`) | Pain points | - |
| Process Forecast to Plan (`F2P`) | Owner | - |
| Process Forecast to Plan (`F2P`) | Priority | - |
| Process Inventory to Delivery (`I2D`) | Purpose | - |
| Process Inventory to Delivery (`I2D`) | Start and end | - |
| Process Inventory to Delivery (`I2D`) | Steps | - |
| Process Inventory to Delivery (`I2D`) | What it records | - |
| Process Inventory to Delivery (`I2D`) | Volume | - |
| Process Inventory to Delivery (`I2D`) | Decisions it supports | - |
| Process Inventory to Delivery (`I2D`) | Pain points | - |
| Process Inventory to Delivery (`I2D`) | Owner | - |
| Process Inventory to Delivery (`I2D`) | Priority | - |
| Process Revenue (`R2P`) | Purpose | - |
| Process Revenue (`R2P`) | Start and end | - |
| Process Revenue (`R2P`) | Steps | - |
| Process Revenue (`R2P`) | What it records | - |
| Process Revenue (`R2P`) | Volume | - |
| Process Revenue (`R2P`) | Decisions it supports | - |
| Process Revenue (`R2P`) | Pain points | - |
| Process Revenue (`R2P`) | Owner | - |
| Process Revenue (`R2P`) | Priority | - |
| Process H2R | Purpose | - |
| Process H2R | Start and end | - |
| Process H2R | Steps | - |
| Process H2R | What it records | - |
| Process H2R | Volume | - |
| Process H2R | Decisions it supports | - |
| Process H2R | Pain points | - |
| Process H2R | Owner | - |
| Process H2R | Priority | - |
| Process H2R | Systems | - |
| Process I2S | Purpose | - |
| Process I2S | Start and end | - |
| Process I2S | Steps | - |
| Process I2S | What it records | - |
| Process I2S | Volume | - |
| Process I2S | Decisions it supports | - |
| Process I2S | Pain points | - |
| Process I2S | Owner | - |
| Process I2S | Priority | - |
| Process I2S | Systems | - |
| Process M2O | Purpose | - |
| Process M2O | Start and end | - |
| Process M2O | Steps | - |
| Process M2O | What it records | - |
| Process M2O | Volume | - |
| Process M2O | Decisions it supports | - |
| Process M2O | Pain points | - |
| Process M2O | Owner | - |
| Process M2O | Priority | - |
| Process M2O | Systems | - |
| Dimension Date (`date`) | Roll-ups | - |
| Dimension Date (`date`) | When it changes | - |
| Dimension Date (`date`) | Owner | - |
| Dimension Date (`date`) | Known data problems | - |
| Dimension Date (`date`) | Master system | - |
| Dimension Customer (`customer`) | Roll-ups | - |
| Dimension Customer (`customer`) | When it changes | - |
| Dimension Customer (`customer`) | Owner | - |
| Dimension Employee (`employee`) | Roll-ups | - |
| Dimension Employee (`employee`) | When it changes | - |
| Dimension Employee (`employee`) | Owner | - |
| Dimension Department (`department`) | Roll-ups | - |
| Dimension Department (`department`) | When it changes | - |
| Dimension Department (`department`) | Owner | - |
| Dimension Department (`department`) | Known data problems | - |
| Dimension Department (`department`) | Master system | - |
| Dimension Item (`item`) | Roll-ups | - |
| Dimension Item (`item`) | When it changes | - |
| Dimension Item (`item`) | Owner | - |
| Dimension Site (`site`) | Roll-ups | - |
| Dimension Site (`site`) | When it changes | - |
| Dimension Site (`site`) | Owner | - |
| Dimension Supplier (`supplier`) | Roll-ups | - |
| Dimension Supplier (`supplier`) | When it changes | - |
| Dimension Supplier (`supplier`) | Owner | - |
| Dimension Supplier (`supplier`) | Known data problems | - |
| Measure Win Rate (`win_rate`) | Benchmark or target | VP Sales |
| Measure Win Rate (`win_rate`) | Trusted report | - |
| Measure Win Rate (`win_rate`) | Subject matter expert | VP Sales |
| Measure Win Rate (`win_rate`) | Changes to past numbers | - |
| Measure Win Rate (`win_rate`) | Definition owner | VP Sales |
| Measure Pipeline Value (`pipeline_value`) | Benchmark or target | VP Sales |
| Measure Pipeline Value (`pipeline_value`) | Trusted report | - |
| Measure Pipeline Value (`pipeline_value`) | Subject matter expert | VP Sales |
| Measure Pipeline Value (`pipeline_value`) | Changes to past numbers | - |
| Measure Pipeline Value (`pipeline_value`) | Definition owner | VP Sales |
| Measure Pipeline Value (`pipeline_value`) | Calculation | - |
| Measure Sales Cycle Days (`sales_cycle_days`) | Benchmark or target | VP Sales |
| Measure Sales Cycle Days (`sales_cycle_days`) | Trusted report | - |
| Measure Sales Cycle Days (`sales_cycle_days`) | Subject matter expert | VP Sales |
| Measure Sales Cycle Days (`sales_cycle_days`) | Changes to past numbers | - |
| Measure Sales Cycle Days (`sales_cycle_days`) | Definition owner | VP Sales |
| Measure On-Time Delivery (`on_time_delivery_rate`) | Benchmark or target | VP Operations |
| Measure On-Time Delivery (`on_time_delivery_rate`) | Trusted report | - |
| Measure On-Time Delivery (`on_time_delivery_rate`) | Subject matter expert | VP Operations |
| Measure On-Time Delivery (`on_time_delivery_rate`) | Changes to past numbers | - |
| Measure On-Time Delivery (`on_time_delivery_rate`) | Definition owner | VP Operations |
| Measure Return Rate (`return_rate`) | Benchmark or target | Director of Customer Service |
| Measure Return Rate (`return_rate`) | Trusted report | - |
| Measure Return Rate (`return_rate`) | Subject matter expert | Director of Customer Service |
| Measure Return Rate (`return_rate`) | Changes to past numbers | - |
| Measure Return Rate (`return_rate`) | Definition owner | Director of Customer Service |
| Measure DSO (days-to-pay proxy) (`dso_days_to_pay_proxy`) | Benchmark or target | Controller |
| Measure DSO (days-to-pay proxy) (`dso_days_to_pay_proxy`) | Trusted report | - |
| Measure DSO (days-to-pay proxy) (`dso_days_to_pay_proxy`) | Subject matter expert | Controller |
| Measure DSO (days-to-pay proxy) (`dso_days_to_pay_proxy`) | Changes to past numbers | - |
| Measure DSO (days-to-pay proxy) (`dso_days_to_pay_proxy`) | Definition owner | Controller |
| Measure Order Fill Rate (`order_fill_rate`) | Benchmark or target | Director of Operations |
| Measure Order Fill Rate (`order_fill_rate`) | Trusted report | - |
| Measure Order Fill Rate (`order_fill_rate`) | Subject matter expert | Director of Operations |
| Measure Order Fill Rate (`order_fill_rate`) | Changes to past numbers | - |
| Measure Order Fill Rate (`order_fill_rate`) | Definition owner | Director of Operations |
| Measure Match Rate (`match_rate`) | Benchmark or target | AP Manager |
| Measure Match Rate (`match_rate`) | Trusted report | - |
| Measure Match Rate (`match_rate`) | Subject matter expert | AP Manager |
| Measure Match Rate (`match_rate`) | Changes to past numbers | - |
| Measure Match Rate (`match_rate`) | Definition owner | AP Manager |
| Measure Supplier On-Time Receipt (`supplier_on_time_receipt_rate`) | Benchmark or target | Purchasing Manager |
| Measure Supplier On-Time Receipt (`supplier_on_time_receipt_rate`) | Trusted report | - |
| Measure Supplier On-Time Receipt (`supplier_on_time_receipt_rate`) | Subject matter expert | Purchasing Manager |
| Measure Supplier On-Time Receipt (`supplier_on_time_receipt_rate`) | Changes to past numbers | - |
| Measure Supplier On-Time Receipt (`supplier_on_time_receipt_rate`) | Definition owner | Purchasing Manager |
| Measure Supplier On-Time Receipt (`supplier_on_time_receipt_rate`) | Source systems | - |
| Measure Supplier On-Time Receipt (`supplier_on_time_receipt_rate`) | Calculation | Purchasing Manager |
| Measure Supplier On-Time Receipt (`supplier_on_time_receipt_rate`) | Date and periods | Purchasing Manager |
| Measure Supplier On-Time Receipt (`supplier_on_time_receipt_rate`) | Breakdowns | - |
| Measure Forecast Accuracy (`forecast_accuracy`) | Benchmark or target | Demand Planning Manager |
| Measure Forecast Accuracy (`forecast_accuracy`) | Trusted report | - |
| Measure Forecast Accuracy (`forecast_accuracy`) | Subject matter expert | Demand Planning Manager |
| Measure Forecast Accuracy (`forecast_accuracy`) | Changes to past numbers | - |
| Measure Forecast Accuracy (`forecast_accuracy`) | Definition owner | Demand Planning Manager |
| Measure Forecast Accuracy (`forecast_accuracy`) | Calculation | - |
| Measure Inventory Accuracy (`inventory_accuracy`) | Benchmark or target | Warehouse Manager |
| Measure Inventory Accuracy (`inventory_accuracy`) | Trusted report | - |
| Measure Inventory Accuracy (`inventory_accuracy`) | Subject matter expert | Warehouse Manager |
| Measure Inventory Accuracy (`inventory_accuracy`) | Changes to past numbers | - |
| Measure Inventory Accuracy (`inventory_accuracy`) | Definition owner | Warehouse Manager |
| Measure Cost Per Shipment (`cost_per_shipment`) | Benchmark or target | Logistics Manager |
| Measure Cost Per Shipment (`cost_per_shipment`) | Trusted report | - |
| Measure Cost Per Shipment (`cost_per_shipment`) | Subject matter expert | Logistics Manager |
| Measure Cost Per Shipment (`cost_per_shipment`) | Changes to past numbers | - |
| Measure Cost Per Shipment (`cost_per_shipment`) | Definition owner | Logistics Manager |
| Measure Cost Per Shipment (`cost_per_shipment`) | Source systems | - |
| Measure Cost Per Shipment (`cost_per_shipment`) | Calculation | Logistics Manager |
| Measure Cost Per Shipment (`cost_per_shipment`) | Date and periods | Logistics Manager |
| Measure Cost Per Shipment (`cost_per_shipment`) | Breakdowns | - |
| Measure Trailing 90-day Revenue (`trailing_90d_revenue`) | Benchmark or target | Controller |
| Measure Trailing 90-day Revenue (`trailing_90d_revenue`) | Trusted report | - |
| Measure Trailing 90-day Revenue (`trailing_90d_revenue`) | Subject matter expert | Controller |
| Measure Trailing 90-day Revenue (`trailing_90d_revenue`) | Changes to past numbers | - |
| Measure Trailing 90-day Revenue (`trailing_90d_revenue`) | Definition owner | Controller |
| Measure Trailing 90-day Revenue (`trailing_90d_revenue`) | Calculation | - |
| Measure Unsettled Invoice Rate (`unsettled_invoice_rate`) | Benchmark or target | Controller |
| Measure Unsettled Invoice Rate (`unsettled_invoice_rate`) | Trusted report | - |
| Measure Unsettled Invoice Rate (`unsettled_invoice_rate`) | Subject matter expert | Controller |
| Measure Unsettled Invoice Rate (`unsettled_invoice_rate`) | Changes to past numbers | - |
| Measure Unsettled Invoice Rate (`unsettled_invoice_rate`) | Definition owner | Controller |
| Measure Revenue (`revenue`) | Benchmark or target | Controller |
| Measure Revenue (`revenue`) | Trusted report | - |
| Measure Revenue (`revenue`) | Subject matter expert | Controller |
| Measure Revenue (`revenue`) | Changes to past numbers | - |
| Measure Revenue (`revenue`) | Definition owner | Controller |
| Measure Revenue (`revenue`) | Calculation | - |
| Measure Customer Match Rate (`customer_match_rate`) | Benchmark or target | Data Steward |
| Measure Customer Match Rate (`customer_match_rate`) | Trusted report | - |
| Measure Customer Match Rate (`customer_match_rate`) | Subject matter expert | Data Steward |
| Measure Customer Match Rate (`customer_match_rate`) | Changes to past numbers | - |
| Measure Customer Match Rate (`customer_match_rate`) | Definition owner | Data Steward |
| Measure Platform Cloud Cost (`cloud_cost`) | Benchmark or target | Platform Lead |
| Measure Platform Cloud Cost (`cloud_cost`) | Trusted report | - |
| Measure Platform Cloud Cost (`cloud_cost`) | Subject matter expert | Platform Lead |
| Measure Platform Cloud Cost (`cloud_cost`) | Changes to past numbers | - |
| Measure Platform Cloud Cost (`cloud_cost`) | Definition owner | Platform Lead |
| Measure Platform Cloud Cost (`cloud_cost`) | Calculation | - |
| Measure Cost Per Order (`cost_per_order`) | Benchmark or target | Director of Sales Operations |
| Measure Cost Per Order (`cost_per_order`) | Trusted report | - |
| Measure Cost Per Order (`cost_per_order`) | Subject matter expert | Director of Sales Operations |
| Measure Cost Per Order (`cost_per_order`) | Changes to past numbers | - |
| Measure Cost Per Order (`cost_per_order`) | Definition owner | Director of Sales Operations |
| Measure Cost Per Order (`cost_per_order`) | Source systems | - |
| Measure Cost Per Order (`cost_per_order`) | Calculation | Director of Sales Operations |
| Measure Cost Per Order (`cost_per_order`) | Date and periods | Director of Sales Operations |
| Measure Cost Per Order (`cost_per_order`) | Breakdowns | - |
| Measure Perfect Order Rate (`perfect_order_rate`) | Benchmark or target | VP Operations |
| Measure Perfect Order Rate (`perfect_order_rate`) | Trusted report | - |
| Measure Perfect Order Rate (`perfect_order_rate`) | Subject matter expert | VP Operations |
| Measure Perfect Order Rate (`perfect_order_rate`) | Changes to past numbers | - |
| Measure Perfect Order Rate (`perfect_order_rate`) | Definition owner | VP Operations |
| Measure Perfect Order Rate (`perfect_order_rate`) | Source systems | - |
| Measure Perfect Order Rate (`perfect_order_rate`) | Calculation | VP Operations |
| Measure Perfect Order Rate (`perfect_order_rate`) | Date and periods | VP Operations |
| Measure Perfect Order Rate (`perfect_order_rate`) | Breakdowns | - |

Flagged for follow-up.

| Item | Note |
|---|---|
| Measure Win Rate (`win_rate`) | A working definition until Sales confirms it (open question Q-B). |
| Measure Pipeline Value (`pipeline_value`) | A working definition until Sales confirms it (open question Q-B). |
| Measure Sales Cycle Days (`sales_cycle_days`) | A working definition until Sales confirms it (open question Q-B). |
| Measure On-Time Delivery (`on_time_delivery_rate`) | Measured against the customer's requested date. Whether the promise should be the requested date or a confirmed ship date is open question 1. |
| Measure Return Rate (`return_rate`) | The denominator (invoiced value) and the date basis (order date) are open questions 16 and 17. |
| Measure DSO (days-to-pay proxy) (`dso_days_to_pay_proxy`) | A days-to-pay proxy, not a balance-based DSO. Open question 2. |
| Measure Order Fill Rate (`order_fill_rate`) | A working definition until the business defines fill rate (open question Q-B). |
| Measure Match Rate (`match_rate`) | Exact quantity and 2% price tolerance are placeholders. Open question 14. |
| Measure Forecast Accuracy (`forecast_accuracy`) | WMAPE is a placeholder for the measure Planning chooses. |
| Measure Inventory Accuracy (`inventory_accuracy`) | Exact match by position is the placeholder tolerance. Open question 15. |
| Measure Trailing 90-day Revenue (`trailing_90d_revenue`) | Exercises a cumulative metric; whether the business wants it is open. |

<!-- requirements:end -->
