# Architecture

A proof of concept for the process performance data model: nine Power BI
dashboards, one per business process, driven by metrics that are defined once
and mapped to dashboards through a seed. How to run it is in
[running_it.md](running_it.md); this document is the design.

---

## 1. What was built

```
  five source systems
        │  ingestion/ - one dlt resource per source table, 6 extraction strategies
        │  landing/   - append-only Parquet archive, replayable
        ▼
  raw.duckdb                              5 schemas · 54 tables · ~248,000 rows
        │
  ┌─────▼──────────────────────────────────────────────────────────┐
  │ staging/            54 models, 1:1 with source tables, generated │
  │                                                                 │
  │   Cleaning only, no business logic. Every landmine in           │
  │   sources.md is handled here and nowhere else: CHAR padding     │
  │   trimmed, 1753-01-01 nulled, HubSpot strings cast, Paycom      │
  │   MM/DD/YYYY parsed, local menus decoded through APLSTD,        │
  │   archived records flagged rather than filtered.                │
  └─────┬──────────────────────────────────────────────────────────┘
        │
  ┌─────▼──────────────────────────────────────────────────────────┐
  │ intermediate/       10 models — crosswalks, resolution, matching │
  │                                                                 │
  │   int_customer_xref          HubSpot ↔ X3, 4 probes, confidence │
  │   int_employee_xref          Paycom deduplicated, then matched  │
  │   int_deal_erp_order_number  CRM→ERP reference repair           │
  │   int_fx_rate                rates recovered from the GL        │
  │   int_shipment_order         shipment → order → customer        │
  │   int_shipment_charge        charge lines → shipment cost       │
  │   int_shipment_milestone     events → milestones, by event_code │
  │   int_sales_order_line       X3 split line tables rejoined      │
  │   int_sales_return_line      returns → the order line they hit  │
  │   int_supplier_invoice_match three-way match, per receipt       │
  └─────┬──────────────────────────────────────────────────────────┘
        │
  ┌─────▼──────────────────────────────────────────────────────────┐
  │ marts/core/         11 models — the data model. Process-agnostic.│
  │                                                                 │
  │   dim_date  dim_customer  dim_site  dim_item  dim_carrier       │
  │   fct_shipment  fct_shipment_event  fct_sales_order_line        │
  │   fct_invoice_line  fct_supplier_invoice_line                   │
  │   fct_inventory_count_line                                      │
  └─────┬──────────────────────────────────────────────────────────┘
        │
  ┌─────▼──────────────────────────────────────────────────────────┐
  │ semantic/           10 metric definitions, tool-neutral YAML     │
  │                                                                 │
  │   One definition per metric. No process field — a metric does   │
  │   not know which dashboards it appears on.                      │
  └─────┬──────────────────────────────────────────────────────────┘
        │  scripts/compile_metrics.py → SQL models, registry seed,
        │                               agent JSON, catalogue
        ├──── seeds/process_metric_map.csv ─────┐
        │     the many-to-many. 7 rows.          │
        │                                        │
  ┌─────▼────────────────────┬───────────────────▼────────────────┐
  │ marts/metrics/ 10 models │ marts/process/  9 views            │
  │ numerator + denominator  │ 3 populated, 6 typed and empty     │
  │ by dimension             │ generated from the seed map        │
  └──────────────────────────┴────────────────────────────────────┘
        │  scripts/export_powerbi.py
  ┌─────▼──────────────────────────────────────────────────────────┐
  │ exports/   Parquet + a generated TMDL model with DAX measures   │
  └─────────────────────────────────────────────────────────────────┘
```

`dbt build` prints the current model and test counts. Diagrams of every layer
are in [data_model.md](data_model.md).

## 2. Why this shape

**One conformed core, nine thin views on top.** The nine processes overlap on
the same facts. Cost Per Order and Cost Per Shipment both consume Pangea
charges. DSO and Return Rate both consume invoices. All nine need customer,
item, site and date.

Nine independently-built marts would mean nine definitions of "customer", nine
chances for revenue to disagree between dashboards, and nine places to fix
every bug. It would also make the AI use case impossible — an agent handed nine
overlapping wide tables with no entity graph cannot reason about them, and will
produce confidently wrong joins.

**Metrics are not owned by processes.** `semantic/metrics/*.yml` has no process
field. The association lives in `seeds/process_metric_map.csv`, so a metric
appearing on two dashboards is two rows in a CSV rather than two definitions
that can drift. This was tested by mapping `cost_per_shipment` — an I2D
metric — onto O2C as well: no metric definition and no generated metric SQL
changed, only `mart_o2c.sql`, and both dashboards returned bit-identical
values.

**The nine views are generated, not written.** `scripts/generate_process_views.py`
reads the seed map and emits one view per process. Six are empty because six
processes have no metrics; they are still generated and still typed, because a
missing view and an empty view are different things and only one of them is a
valid state.

---

## 3. Runbook: adding a metric

This is the number the design is optimising. The step-by-step guide, with two
worked examples run against this repo, is
[adding_a_metric.md](adding_a_metric.md). In summary:

- **The fact already has the columns** — the common case. One YAML file in
  `semantic/metrics/`, one row in `seeds/process_metric_map.csv`, then
  `python scripts/regenerate.py && dbt build`. The compiler writes the SQL
  model, catalogue entry, JSON contract and registry seed; the view generator
  puts it on the dashboard; the next `export_powerbi.py` run adds the DAX
  measure. No fact model, dimension, other metric or other dashboard changes.
- **The fact has the inputs but not the exact column** — a comparison between
  two columns, or arithmetic. Add the column to the fact first; the metric
  grammar deliberately cannot express it.
- **No fact exists at the right grain.** Build the fact, test its grain, bind it
  to the conformed dimensions in `semantic/models.yml`, then add the metric.

### When the data does not exist: register it as blocked

```yaml
name: perfect_order_rate
label: Perfect Order Rate
status: blocked
description: >
  The share of orders delivered complete, on time, damage-free and correctly
  invoiced.
grain: To be determined. Most likely one sales order.
base_model: null
numerator: null
denominator: null
filters: []
dimensions: [date, customer, site]
owner: TBD
blocked_reason: >
  Requires a damage or claims source, which does not exist in any of the five
  systems. The other three components are computable today.
unblock_requires:
  - A damage/claims transaction source keyed to shipment or order.
```

It costs nothing, it appears in the catalogue and in the JSON contract, and the
dashboard renders it as a tile that states why it is empty. The compiler
enforces that a blocked metric carries no SQL, and a dbt test asserts the same
thing against the warehouse. Return Rate, Match Rate and Inventory Accuracy
all started this way and were unblocked by sourcing the missing documents —
without any change to the compiler or the grammar.

### What the compiler will refuse

Governance is enforced at compile time, not by review:

- A metric whose filename does not match its `name`.
- Two metrics with the same name.
- A missing required field, including `owner` — which stays `TBD` on every
  metric, visibly, rather than resolving to silence.
- A dimension not in `semantic/dimensions.yml`, or one the base model has no
  binding for. This is the check that stops "customer" meaning three different
  things on three dashboards.
- A `provisional` metric with no `provisional_reason`.
- A `blocked` metric with no `blocked_reason`, or one that carries SQL anyway.
- An aggregation outside `sum | count | count_distinct | avg | min | max`.
- A numerator or denominator that is an expression rather than a bare column,
  or a filter op outside the fixed set (`is_true`, `is_null`, `eq`, `gte`,
  `in` and so on). Anything the DAX renderer cannot translate exactly is a
  build error rather than a wrong number.
- With `target/catalog.json` present (`dbt docs generate`), a column that does
  not exist on the base model.

---

## 4. Entity resolution

Two identity problems, both solved as first-class inspectable models rather
than as joins buried inside a dimension. The matching is uncertain, and the
business needs to see the uncertainty rather than inherit it.

### Customer: HubSpot ↔ Sage X3

No shared key. Four probes, in descending precision.

Two counts, kept apart because they answer different questions. **Probe hits**
is every pair a probe fires on; **pairs credited** is pairs whose *strongest*
probe was that one, after `best_method_per_pair` collapses duplicates. The gap
between the columns is what each tier adds over the tiers above it, which is
the number that matters when tuning.

| Probe | Confidence | Probe hits | Pairs credited | What it catches |
|---|---|---|---|---|
| `exact_name` | 0.95 | 171 | 171 | `upper(trim(name))` equality |
| `alnum_name` | 0.90 | 183 | 12 | punctuation and spacing ignored — "Halcyon Hydraulics, LLC" |
| `domain_stem` | 0.75 | 250 | 84 | the HubSpot domain stem prefixes the ERP name |
| `core_name` | 0.60 | 310 | 43 | legal suffix stripped as well |

The suffix list `core_name` strips lives in `seeds/legal_suffix.csv`, not in a
regex — entity resolution is the thing a client iterates on hardest once real
names arrive (GmbH, Pty, SA, BV, Holdings), and every other business-tunable
list in this project is a seed or a var.

`int_customer_xref` emits one row per candidate pair with `match_method`,
`confidence`, `is_ambiguous` and `is_selected`. Nothing is discarded silently.

**Result: 88.1% of HubSpot companies get a candidate, up from 65.8% on exact
name alone.**

| | Count | Share |
|---|---|---|
| HubSpot companies | 260 | |
| With a match candidate | 229 | 88.1% |
| **Unmatched — no ERP counterpart** | **31** | **11.9%** |
| Ambiguous at their best confidence tier | 15 | 5.8% |
| X3 customers claimed by more than one CRM company | 27 | 12.3% |

`core_name` is deliberately last. It has the highest recall and it is the only
probe that generates real ambiguity — "Redstone Machine Works LLC" and
"Redstone Machine Works Inc" are legally distinct entities with the same core
name. 71 companies match more than one X3 customer on core name alone; the
domain stem, which retains the first characters of the legal suffix, resolves
62 of them.

**Survivorship** (assumed, open question 7): X3 wins financial attributes —
credit limit, payment terms, currency, accounting code, sales rep. HubSpot wins
firmographics — industry, employee count, annual revenue, domain.

`dim_customer` carries `source_scope` so the result is readable straight off the
dimension: 197 `both`, 23 `erp_only`, 31 `crm_only`. The 31 unmatched CRM
companies stay **in** the dimension. Dropping them would make the unmatched rate
look like zero, which is exactly the number the business needs to see.

The unmatched rate is published as a metric — `customer_unmatched_rate`,
registered but mapped to no process, which also exercises the reverse of the
empty-dashboard case.

### Employee: Paycom ↔ X3 ↔ HubSpot

The interesting finding here is that the problem is not the one the source
documentation describes.

**Paycom contains duplicate people.** 12 of its 150 employee rows are the same
person twice — same legal name, same `work_email`, two different
`employee_code` values. The roster describes 138 people, not 150.

This breaks both candidate keys at once, and the order of operations decides
whether you notice:

| | Rows returned | Reps in X3 |
|---|---|---|
| Match X3 reps to Paycom on name, then look | 30 | 28 |
| Deduplicate Paycom first, then match | **28** | 28 |

Same for HubSpot: 22 owners, 22 distinct emails, and still 23 join rows because
one owner hits a duplicated employee.

`int_employee_xref` therefore uses Paycom as the spine, collapses duplicates on
`work_email` first (surviving row = earliest hire), and only then runs the
cross-system probes:

| Probe | Confidence | Matches |
|---|---|---|
| `work_email` → HubSpot owner | 0.99 | 22, all unambiguous |
| `person_name` → X3 rep | 0.70 | 28, all unambiguous |

`duplicate_record_count` is published on every row, so the Paycom roster
problem stays visible to the people who can fix it in Paycom.

The email link between HubSpot owners and Paycom is **not in the source join
map** and it is far better than the name match the map proposes.

### Two other crosswalks worth knowing about

**`pangea.shipment.customer_name` matches `BPCUSTOMER.BPCNAM_0` on all 220
distinct values.** Also not in the join map. It cannot recover the order, but it
recovers the customer for the 511 shipments (14.6%) that carry no resolvable
order reference — which is why customer resolution on `fct_shipment` is 100%
while order resolution is 85.4%. Those are different coverage numbers and
conflating them would overstate what can be attributed to an order.

**CRM-to-ERP order references repair mechanically.** 145 of 238 closed-won deals
carry a reference and only 96 join as-is. `int_deal_erp_order_number` fixes
three failure modes, and every repaired reference resolves to a real order.
The flags are independent booleans, so a reference that is both split out of a
two-order field *and* lowercased would appear in both counts:

| Repair | Rows | Resolve |
|---|---|---|
| none — `as_is` | 96 | 96 |
| `was_split` — `"SOUS25002068 / SOUS24001818"` | 44 | 44 |
| `was_case_corrected` — `sous26001710` | 17 | 17 |
| `was_prefix_restored` — `US25000718` → `SOUS25000718` | 10 | 10 |

96 → 145 deals, which is every deal carrying a reference at all. The remaining
gap is the 93 closed-won deals with no reference, which is a process problem in
HubSpot rather than a data problem here.

---

## 5. One definition, two engines

The high-risk idea in the design was generating both the warehouse SQL and the
Power BI DAX from one metric definition. It works: `compile_metrics.py` writes
the `mtr_*` SQL models, and `export_powerbi.py` imports the same compiler's
`dax_measure()` to write every measure into the Power BI model. No measure
anywhere is hand-written. Three things came out of building it.

**Raw SQL expressions in the registry would have killed it.** A free-text SQL
expression compiles to SQL trivially and to DAX not at all — there is no safe
general translation, and a wrong one produces a measure that compiles, returns
a number, and is quietly incorrect. The registry therefore uses a structured
form: each side is an aggregation over a bare column, and filters are
`{column, op, value}` triples over a fixed op set that each renderer maps from
a table. The cost is that the registry cannot express arbitrary arithmetic.
That is the right trade: when a metric needs arithmetic, the arithmetic belongs
in the fact model as a column, which is also where it becomes testable.

**Not every metric is re-aggregatable.** Cost Per Order has a `count_distinct`
denominator. A pre-aggregated SQL model is correct at the grain it was
aggregated to and wrong if summed to a coarser one — an order spanning two
sites would be counted twice. The compiler detects this: the SQL model carries
a header warning, the registry records `is_reaggregatable: false`, and the DAX
uses `DISTINCTCOUNT` over the fact, which stays correct at every grain. This is
the single most common way a semantic layer produces confidently wrong numbers,
and it only becomes visible when you generate two targets from one definition.

**Generating the whole Power BI model, not just the measures, is the bigger
win.** Tables, columns, data types, `summarizeBy` defaults, display folders and
relationships all generate from the warehouse schema. A column renamed in dbt
and not in Power BI breaks a report; a relationship pointed at the wrong column
produces a plausible wrong number. Generating the model removes both.

MetricFlow and Cube targets were also prototyped and removed because nothing
consumed them. One result is worth keeping: MetricFlow could not express
`customer_unmatched_rate`, because it requires a time dimension on every
measure and `dim_customer` has none. Had the metrics been written natively in
MetricFlow, that metric would not exist. That is the argument for keeping the
registry tool-neutral whichever semantic-layer product is chosen (open
question 5): adopting one is a new renderer, not a rewrite.

### Where measure logic is allowed to live

Power BI is meant to be a visualisation wrapper, so metrics can serve other
frontends and the AI use case. The useful form of that rule is not "no
computation in Power BI" — compiled DAX computing from the star is correct at
every grain, keeps the degenerate attributes (`service_level`,
`transport_mode`, `destination_state`) sliceable, and keeps drill-through to
the shipment row. The rule that actually protects the goal is narrower:

> **No measure logic is authored in Power BI, and none is authoritative there.**
> Compiled DAX is acceptable the way compiled code is acceptable: nobody edits
> it, and it regenerates from `semantic/metrics/`.

| Where | What belongs there |
|---|---|
| **Power BI, authored** | Presentation only — number formatting, conditional colour, sort order, how a blocked tile renders. |
| **Registry only** | Anything that changes what the number means: filters, grain, aggregation, base model, cost pool, promise basis. |

**What makes that safe** is that the compilation is total and tested.
`SEMANTIC_FIELDS` and `CONSUMES` in `scripts/compile_metrics.py` declare which
definition fields each renderer honours, and validation fails if a metric sets
a field a renderer would silently ignore. That check exists because the
failure already happened: the metric-level `filters` list once reached only
the SQL target, so Cost Per Order computed \$1,560.78 in the warehouse and
\$1,830.79 in the DAX — a 17.3% divergence. 511 shipments with no order
reference were excluded by one engine and included by the other.

| Rung | Catches | Status |
|---|---|---|
| L1 · field-consumption assert | silently dropped fields | in `validate()` |
| L2 · structured filters | translation bugs, by construction | in the grammar |
| L3 · `mtr_*` vs base fact | re-aggregation and aggregation errors | `scripts/test_metric_parity.py`, every build |
| L4 · execute the DAX and diff | everything else | queries generated, needs a Power BI runtime |

L4 is the only rung that proves the two *engines* agree rather than that the
two *definitions* agree. Its queries are generated into
`exports/powerbi/parity/` with the warehouse's answer beside each, so the gate
exists the day someone first opens the model — a manual thirty-minute step per
release, described in [powerbi_model.md](powerbi_model.md).

---

## 6. The AI use case

An agent should be able to answer "what was on-time delivery for the Reno site
last quarter" without being handed SQL or a data dictionary.
`scripts/ask_metric.py` demonstrates that it can, reading only
`exports/semantic/metric_registry.json`.

```
$ python scripts/ask_metric.py on_time_delivery_rate \
      --where site.city=Reno --period 2026-Q2

On-Time Delivery (active)

         74.3%    (n = 218)

  CAVEAT: The 128 undelivered shipments (109 EXCEPTION, 19 IN_TRANSIT) are
    excluded from the denominator, which means a shipment that fails
    outright cannot make this metric worse...
```

There is no metric knowledge in that script. It resolves the metric, its base
model, its conformed dimensions and their attributes from the registry, writes
the SQL itself, and runs it. Point it at a registry with fifty metrics and it
answers fifty kinds of question.

Four behaviours matter more than the number:

**It refuses invalid slices.** `--where item.item_status=Active` on On-Time
Delivery returns *"On-Time Delivery cannot be sliced by 'item'. It supports:
date, customer, site, carrier"*. An agent cannot silently produce a figure from
a join that does not hold — which is exactly what happens when an agent is
handed nine wide tables and left to infer the relationships.

**It reports blocked metrics as blocked.** None is blocked today, but a blocked
metric returns no number: it prints the `blocked_reason` and what would unblock
it. A model that cannot see a gap will fill it with something plausible.

**It carries the caveats with the number.** The DSO proxy arrives labelled
provisional, with "publish alongside `unsettled_invoice_rate`" attached. Cost
Per Order arrives flagged as not re-aggregatable, and is computed from the base
fact rather than by summing a pre-aggregate.

**It knows which dashboards a metric is on** — read from the seed map, not from
the metric definition, which is the same separation the whole design rests on.

If a semantic-layer product with an API is adopted, it replaces this script;
the registry is the contract either way.

---

## 7. Data quality: four warnings, on purpose

Relationship tests on the join map's dashed lines are set to `warn` with a
documented threshold and a note saying what a change would mean. Deleting them
would hide the finding; erroring on them would make the build permanently red.

| Warning | Rows | What it means |
|---|---|---|
| `pangea.shipment.reference_number` → `SORDER` | 264 | Customer POs in the reference field. Errors above 600. |
| `netstock.item_location` → `ITMMASTER` | 35 | Items planned but not mastered. Errors above 50. |
| Paycom `work_email` uniqueness | 12 | Duplicate people in the roster. Errors above 15. |
| `paycom.gl_mapping` → `GACCENTRYD` | 11 | **The join map draws this as a solid line. It is not one.** Payroll accounts 50100–50140 and 21500–21700 do not exist in the GL. Errors above 11. |

That last one is a finding, not a nuisance: payroll is not posted to the general
ledger in this extract, which is part of why a fully-loaded Cost Per Order is
not computable.

### Reconciliation

`fct_invoice_line.line_net_amount_usd` — invoices less credit memos — sums to
**216,389,996.78** and reconciles to GL account 41000 (**216,389,996.88**)
**within \$0.10**. The residual is FX rounding: the fact converts each line
with a `decimal(18,6)` rate against a `decimal(18,4)` amount, while the GL
carries an amount already converted at posting.

That is asserted rather than claimed:
`tests/assert_invoice_lines_reconcile_to_gl_revenue.sql` fails above a \$1.00
tolerance — comfortably above the residual, comfortably below anything that
would be a real difference. It is the one figure a CFO will check, which is why
it is a test and not a sentence.

### Current values

Each reconciles between its metric model and its base fact on every build
(`scripts/test_metric_parity.py`).

| Metric | Value | Status |
|---|---|---|
| On-Time Delivery | 75.6% | active |
| Cost Per Shipment | $1,564.18 | active |
| Inventory Accuracy | 93.4% | provisional |
| DSO (days-to-pay proxy) | 48.0 days | provisional |
| Return Rate | 1.27% | provisional |
| Cost Per Order | $1,560.78 | provisional |
| Match Rate | 70.7% | provisional |
| Unsettled Invoice Rate | 13.8% | active |
| Order Reference Coverage | 85.4% | active |
| Unmatched CRM Customers | 11.9% | active |

---

## 8. What is generated and what is hand-written

Most of the SQL in this project is generated. That is a deliberate choice and
it is worth being explicit about, because generated code that nobody can
regenerate is worse than hand-written code.

| Generated by | Output | Regenerate with |
|---|---|---|
| `scripts/generate_staging.py` | 54 staging models | edit the column spec, re-run |
| `scripts/compile_metrics.py` | 10 metric models, registry seed, agent JSON, catalogue | edit the metric YAML, re-run |
| `scripts/generate_process_views.py` | 9 process views | edit the seed map, re-run |
| `scripts/export_powerbi.py` | Parquet + the TMDL model, DAX measures included | re-run after `dbt build` |
| `scripts/freeze_schema_contract.py` | the pinned source schema contract | re-run, then **review** |

`scripts/regenerate.py` runs the first four generators in order, because they
have an ordering dependency — editing a metric definition changes the compiled
registry, which changes the process views. `--check` fails if regeneration
moves the working tree. That is the CI guard, and it exists because the failure
happened once: a blocked reason was edited, the metric artefacts were
recompiled, the process views were not, and `mart_s2p.sql` sat in the repo for
a commit carrying text that no longer matched its definition. Nothing broke,
because a stale generated file is still valid SQL. That is what makes it
dangerous.

### What actually reads each output

| Output | Consumed by |
|---|---|
| `mtr_*` SQL models | the `mart_*` views, `ask_metric.py`, the parity test |
| `metric_registry` seed | the `mart_*` views, dbt referential tests, the Power BI model |
| agent JSON | `ask_metric.py` |
| DAX / TMDL | the Power BI model — generated, not yet opened in Power BI Desktop |

`export_powerbi.py` writes Parquet for the `mtr_*` and `mart_*` tables as well,
but **the TMDL model loads only the eleven core tables and three seed tables**.
The dashboard composes its tiles from `process_metric_map` and computes every
value in DAX from the star. The metric and process tables ship beside the model
for reference and are not read by it.

**Hand-written and staying that way**: the 10 intermediate models, the 11 core
models, all model YAML, the seeds, and the singular tests. That is where the
thinking is. Everything generated is mechanical, and mechanical code written by
hand is where inconsistency creeps in precisely because nobody reviews the
forty-third near-identical file.

Every generated file carries a banner naming the script and the input.

---

## 9. What was not built, and why

- **The other four conformed dimensions** — `dim_supplier`, `dim_employee`,
  `dim_gl_account`, `dim_deal_stage` — and the seven facts named in §3. No
  active metric needs them. Building them now would be building unread code.
- **The other six process views are empty by design**, not by omission. Six
  processes have no metrics.
- **Two intermediate models are built but unconsumed** — `int_employee_xref`
  and `int_deal_erp_order_number`. No active metric needs an employee or a CRM
  deal. They are kept because their findings are governance results in their
  own right (150 Paycom rows describe 138 people; 96 recoverable deals become
  145) and because the resolution is then done and tested for the first H2R,
  P2C or M2O metric that needs it.
- **The other metrics** (nine dashboards × four slots, minus seven defined).
  Undefined and explicitly out of scope. Inventing them would be the single
  most expensive mistake available here.
- **An opened Power BI file.** The model generates; it has not been opened in
  Power BI Desktop in this environment, and the docs say so.
- **Slowly changing dimensions.** Every conformed dimension is Type 1, so two
  years of history carry today's attributes. Snapshots on the three sources
  that would feed a Type 2 dimension run and accumulate, but nothing consumes
  them. This is the one gap that gets more expensive with time rather than
  staying flat — see open question 11.
- **Role-playing date relationships.** `delivered_date_key`, `payment_date_key`
  and `requested_delivery_date_key` exist on the facts but have no Power BI
  relationship. "DSO by settlement month" and "on-time by delivery month" are
  the two most obvious follow-ups, and neither is answerable in the exported
  model. Each needs an inactive relationship plus a `USERELATIONSHIP` measure.
- **Incremental materialisation.** Everything is a full refresh, which is
  correct at this volume. The ingestion asymmetry that will drive the real
  decision is documented in [ingestion.md](ingestion.md).

### Declared but not built

Things the design commits to in writing and does not yet do. Each is declared
where someone would look for it, so it gets built rather than rediscovered.

| What | Declared where | Blocked on |
|---|---|---|
| **Delete reconciliation.** Merge disposition never removes a row, so a row hard-deleted upstream persists forever. | `TableSpec.reconcile_keys` on every merge table, shown as a `deletes` column in `run_ingestion.py --explain` | Nothing. It is a periodic key diff against the source, and it is the largest single gap in the ingestion design. |
| **The FX company-currency restriction.** `int_fx_rate` derives a document-to-*company*-currency rate and publishes it as a reporting-currency rate. | `COMPANY.CUR_0` on the extraction spec; `tests/assert_fx_rate_is_not_identity_for_foreign_currency.sql` catches the symptom meanwhile | The column does not exist in the mock. Open question 10. |
| **L4 parity — executing the generated DAX.** | Queries in `exports/powerbi/parity/` with expected values | A Power BI runtime. |
| **Landing archive compaction.** The projection rescans the whole archive every run, so it degrades with archive *age* rather than source volume. | [ingestion.md §8](ingestion.md) | Nothing — it is correct until the archive is large, and premature until then. |

---

## 10. The open questions

Full detail in [open_questions.md](open_questions.md). Sixteen are config or
definition changes whenever the business answers. One is not.

| # | Question | Assumed | Encoded as |
|---|---|---|---|
| 1 | On-Time Delivery promise basis | Carrier promise | the metric's filter column; both flags on `fct_shipment` |
| 2 | DSO basis | Days-to-pay proxy | metric `status: provisional` |
| 3 | Cost Per Order cost pool | Fulfillment only | `var: cost_per_order_pool` |
| 4 | Fiscal calendar | Fiscal = calendar | `var: fiscal_year_start_month` |
| 5 | Semantic layer tool | Tool-neutral registry | the registry itself |
| 6 | Power BI topology | One shared model | recommendation |
| 7 | Customer survivorship | X3 financial, HubSpot firmographic | `dim_customer` |
| 8 | Metric ownership | Unassigned, roles proposed | `owner: TBD`, enforced |
| 9 | What Pangea is | Freight visibility platform | source description |
| 10 | Currency policy | USD at the GL-derived rate | `var: reporting_currency` |
| 11 | As-was vs as-is attribution | Type 1 throughout | **unrecoverable, and rising** |
| 12 | Can one order ship twice? | One shipment per order | one metric model |
| 13 | Is the Pangea customer name typed? | A reliable key | attribution falls to 85.4% |
| 14 | Three-way match tolerance | Exact quantity, 2% price | `var: match_*_tolerance_pct` |
| 15 | Inventory accuracy tolerance and basis | Exact match, by position | `var: inventory_accuracy_tolerance_pct` |
| 16 | Return Rate denominator | Invoiced value | `var: return_rate_basis` |
| 17 | Return Rate date basis | Order date | one metric definition |

**Question 11 is the exception.** A Type 2 dimension can only be built forward
from its first snapshot, and no source in the estate carries effective dating,
so deferring that decision does not defer the cost — it deletes the history the
decision would need. Snapshots on the three candidate sources run and
accumulate against that day, which costs one command in the schedule and buys
the option.
