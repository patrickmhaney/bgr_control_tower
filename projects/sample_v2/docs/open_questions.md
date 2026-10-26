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
