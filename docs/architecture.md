# Control Tower — analytical data model

A proof of concept for the process performance data model: nine Power BI
dashboards, one per business process, driven by metrics that are defined once
and mapped to dashboards through a seed.

## Start here

| Document | What it answers |
|---|---|
| **[metric_feasibility.md](metric_feasibility.md)** | Can the seven defined metrics actually be computed? Read this first — the answer is "three cannot", and it is the most important finding on the project. |
| **[open_questions.md](open_questions.md)** | The ten things the data could not answer, what was assumed instead, and what it costs to reverse each assumption. |
| **[running_it.md](running_it.md)** | Hands on: running the pipeline, stepping through it, and querying the result. |
| **[ingestion.md](ingestion.md)** | Source systems to raw. The extraction spec, what is real vs simulated, per-system difficulty, and the pitfalls that actually bit. |
| **[data_model.md](data_model.md)** | The pictures. Source ERDs, the cross-system join map with measured match rates, the star schema, and the pipeline DAGs. |
| **[semantic_layer_spike.md](semantic_layer_spike.md)** | Can one metric definition generate both the SQL and the Power BI measures? Yes — and the three things that finding out surfaced. |
| **[metric_catalog.md](metric_catalog.md)** | Generated. Every metric, its definition, grain, owner and lineage. |
| **[powerbi_model.md](powerbi_model.md)** | The semantic model structure, the I2D dashboard, and the one-model-vs-nine recommendation. |
| this document | The architecture, the metric-addition runbook, and entity resolution. |

```bash
python3 -m venv .venv
. .venv/bin/activate                     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export DBT_PROFILES_DIR="$PWD"
export BGR_CONTROL_TOWER_HOME="$PWD"         # so dbt works from any directory
dbt deps
python run_ingestion.py                  # source systems -> raw
dbt build                                # 80 models, 207 tests
dbt docs generate && dbt docs serve
```

Full setup, platform notes and troubleshooting: [running_it.md](running_it.md).

To build without running ingestion, read the source systems directly:
`dbt build --vars '{source_database: mock_sources}'`. `scripts/verify_ingestion.py`
builds both ways and asserts every metric is identical.

---

## 1. What was built

```
  five source systems
        │  ingestion/ - 46 dlt resources, 6 extraction strategies
        │  landing/   - append-only Parquet archive, replayable
        ▼
  raw.duckdb                                          233,150 rows
        │
  ┌─────▼──────────────────────────────────────────────────────────┐
  │ staging/            46 models, 1:1 with source tables          │
  │                                                                 │
  │   Cleaning only, no business logic. Every landmine in           │
  │   README.md is handled here and nowhere else: CHAR padding      │
  │   trimmed, 1753-01-01 nulled, HubSpot strings cast, Paycom      │
  │   MM/DD/YYYY parsed, local menus decoded through APLSTD,        │
  │   archived records flagged rather than filtered.                │
  └─────┬──────────────────────────────────────────────────────────┘
        │
  ┌─────▼──────────────────────────────────────────────────────────┐
  │ intermediate/        8 models — crosswalks and entity resolution │
  │                                                                 │
  │   int_customer_xref        HubSpot ↔ X3, 4 probes, confidence   │
  │   int_employee_xref        Paycom deduplicated, then matched    │
  │   int_deal_erp_order_number  CRM→ERP reference repair           │
  │   int_fx_rate              rates recovered from the GL          │
  │   int_shipment_order       shipment → order → customer          │
  │   int_shipment_charge      charge lines → shipment cost         │
  │   int_shipment_milestone   events → milestones, by event_code   │
  │   int_sales_order_line     X3 split line tables rejoined        │
  └─────┬──────────────────────────────────────────────────────────┘
        │
  ┌─────▼──────────────────────────────────────────────────────────┐
  │ marts/core/          9 models — the data model. Process-agnostic.│
  │                                                                 │
  │   dim_date  dim_customer  dim_site  dim_item  dim_carrier       │
  │   fct_shipment  fct_shipment_event                              │
  │   fct_sales_order_line  fct_invoice_line                        │
  └─────┬──────────────────────────────────────────────────────────┘
        │
  ┌─────▼──────────────────────────────────────────────────────────┐
  │ semantic/            10 metric definitions, tool-neutral YAML    │
  │                                                                 │
  │   One definition per metric. No process field — a metric does   │
  │   not know which dashboards it appears on.                      │
  └─────┬──────────────────────────────────────────────────────────┘
        │  scripts/compile_metrics.py  → 8 generated artefacts
        │
        ├──── seeds/process_metric_map.csv ─────┐
        │     the many-to-many. 7 rows.          │
        │                                        │
  ┌─────▼────────────────────┬───────────────────▼────────────────┐
  │ marts/metrics/  7 models │ marts/process/  9 views            │
  │ numerator + denominator  │ 3 populated, 6 typed and empty     │
  │ by dimension             │ generated from the seed map        │
  └──────────────────────────┴────────────────────────────────────┘
        │
  ┌─────▼──────────────────────────────────────────────────────────┐
  │ exports/   Parquet + generated TMDL + Cube schema + JSON        │
  └─────────────────────────────────────────────────────────────────┘
```

<!-- BUILD-STATS -->
80 models, 214 data tests, 5 seeds, 3 snapshots and 46 sources. 210 tests pass, 4 warn with documented thresholds, 0 error.

<sub>Counts generated by `scripts/update_build_stats.py` from the last `dbt build`. `regenerate.py --check` fails if they drift.</sub>
<!-- /BUILD-STATS -->

dbt also registers MetricFlow metrics across two semantic models, all
generated. One metric cannot be expressed there for want of an aggregation
time dimension, and the generated file names it in its header - see
[semantic_layer_spike.md](semantic_layer_spike.md).

## 2. Why this shape

**One conformed core, nine thin views on top.** The nine processes overlap on
the same facts. Cost Per Order and Cost Per Shipment both consume Pangea
charges. DSO and anything in R2P both consume invoices. All nine need customer,
item, site and date.

Nine independently-built marts would mean nine definitions of "customer", nine
chances for revenue to disagree between dashboards, and nine places to fix
every bug. It would also make the AI use case impossible — an agent handed nine
overlapping wide tables with no entity graph cannot reason about them, and will
produce confidently wrong joins.

**Metrics are not owned by processes.** `semantic/metrics/*.yml` has no process
field. The association lives in `seeds/process_metric_map.csv`, so a metric
appearing on two dashboards is two rows in a CSV rather than two definitions
that can drift.

This is asserted, not assumed. `scripts/test_metric_reuse.py` maps
`cost_per_shipment` — an I2D metric — onto O2C, rebuilds, and checks that no
metric definition changed, no generated SQL changed, exactly one presentation
view changed, and both dashboards return bit-identical values. Then it puts
everything back.

```
$ python scripts/test_metric_reuse.py
  [PASS] no metric definition changed - the metric is still defined exactly once
  [PASS] no generated metric SQL model changed - no second implementation appeared
  [PASS] exactly one presentation view changed, and it is mart_o2c.sql
  [PASS] cost_per_shipment now returns rows on O2C
  [PASS] identical on both dashboards: I2D 1564.1803049301795 vs O2C 1564.1803049301795
  [PASS] two map rows, one definition: [('I2D', 'M3'), ('O2C', 'M4')]
  [PASS] restored - cost_per_shipment is off O2C again
  [PASS] project restored to its original state
```

**The nine views are generated, not written.** `scripts/generate_process_views.py`
reads the seed map and emits one view per process. Six are empty because six
processes have no metrics; they are still generated and still typed, because a
missing view and an empty view are different things and only one of them is a
valid state.

---

## 3. Runbook: adding a metric

This is the number the design is optimising. Here is exactly what you do.

### The common case: a metric on a fact that already exists

**One file, one line, two commands.**

**Step 1.** Write `semantic/metrics/<metric_name>.yml`:

```yaml
name: average_order_value
label: Average Order Value
status: active

description: >
  The average net value of a sales order line, in reporting currency.
  <One paragraph, in business language. This is what an analyst reads
  when they want to know what the number means.>

grain: One sales order line.

base_model: fct_sales_order_line

numerator:
  agg: sum
  expression: line_net_amount_usd
  label: Order value

denominator:
  agg: count
  expression: sales_order_number
  label: Order lines

filters: []
dimensions: [date, customer, site, item]

format: currency_usd
decimals: 2
direction: higher_is_better

owner: TBD
owner_proposed: Director of Sales Operations

lineage_notes: >
  <Source columns, and every assumption you made. This is the field that
  makes the metric auditable a year from now.>

blocked_reason: null
```

**Step 2.** Add one line to `seeds/process_metric_map.csv`:

```
O2C,average_order_value,M4,4
```

**Step 3.**

```bash
python scripts/compile_metrics.py
python scripts/generate_process_views.py
dbt build
```

That is the whole task. The compiler wrote the SQL model, the dbt semantic
model, the DAX, the TMDL, the Cube schema, the JSON contract, the catalogue
entry and the registry seed. The view generator put it on the O2C dashboard.
`dbt build` tested it and the referential integrity test between the seed and
the registry caught the typo if you made one.

**Nothing else was touched.** No fact model, no dimension, no other metric, no
other dashboard.

### The less common case: the fact does not exist yet

Add the fact first, then the metric above. Three files:

1. `models/marts/core/fct_<event>.sql` — atomic grain, stated in a comment at
   the top and in the YAML description.
2. An entry in `models/marts/core/_core__models.yml` — the grain in the
   description, a uniqueness test on the declared grain, and a `relationships`
   test on every dimension key.
3. An entry in `semantic/models.yml` binding the fact to the conformed
   dimensions:

```yaml
  fct_purchase_order_line:
    label: Purchase Order Line
    grain: One purchase order line.
    description: X3 purchase order lines with expected and actual receipt.
    dimensions:
      date: order_date_key
      site: site_code
      item: item_code
    degenerate:
      order_status: order_status
```

Facts already named and grained, so this decision is made once rather than
rediscovered: `fct_inventory_movement` (`STOJOU.ROWID`),
`fct_inventory_balance` (item × site × lot snapshot), `fct_purchase_order_line`
(`POHNUM_0` + `POPLIN_0`), `fct_gl_entry_line` (`NUM_0` + `LIN_0`),
`fct_forecast` (item × location × period snapshot), `fct_deal_stage_change`
(`deal_id` + transition), `fct_payroll_earning` (`check_id` + `earning_code`).

### The case you will actually hit first: the metric is blocked

Register it anyway.

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
dashboard renders it as a populated tile that states why it is empty. The
compiler enforces that a blocked metric carries no SQL, and a dbt test asserts
the same thing against the warehouse.

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
- A filter that cannot be safely translated to DAX. It raises rather than
  guessing, because a filter that silently mistranslates is worse than one that
  fails to compile.

---

## 4. Entity resolution

Two identity problems, both solved as first-class inspectable models rather
than as joins buried inside a dimension. The matching is uncertain, and the
business needs to see the uncertainty rather than inherit it.

### Customer: HubSpot ↔ Sage X3

No shared key. Four probes, in descending precision:

Two counts, kept apart because they answer different questions and a reader
comparing them across documents otherwise concludes one is wrong. **Probe hits**
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

The interesting finding here is that the problem is not the one the README
describes.

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

The email link between HubSpot owners and Paycom is **not in the README's join
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
three failure modes, and every repaired reference resolves to a real order:

Counted per flag, not per bucket. `was_split`, `was_case_corrected` and
`was_prefix_restored` are independent booleans, so a reference that is both
split out of a two-order field *and* lowercased appears in both counts. No deal
in this extract is both — which is exactly why a priority chain looked correct
here and would have stopped being correct in production.

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

## 5. Where measure logic is allowed to live

Power BI is meant to be a visualisation wrapper, so metrics can serve other
frontends and the AI use case. The useful form of that rule is not "no
computation in Power BI" — compiled DAX computing from the star is correct at
every grain, keeps the degenerate attributes (`service_level`,
`transport_mode`, `destination_state`) sliceable, and keeps drill-through to
the shipment row. Pointing Power BI at the pre-aggregated `mtr_*` tables
instead would buy purity by deleting analysis surface. The rule that actually
protects the goal is narrower:

> **No measure logic is authored in Power BI, and none is authoritative there.**
> Compiled DAX is acceptable the way compiled code is acceptable: nobody edits
> it, and it regenerates from `semantic/metrics/`. What makes that safe is that
> the compilation is **total** and **tested**.

Neither was true when this was first written, and it cost a wrong number — see
the drift note below. Both are now enforced.

| Where | What belongs there |
|---|---|
| **Power BI, authored** | Presentation only — number formatting, conditional colour, sort order, display folders, how a blocked tile renders. Do not push these into dbt. |
| **DAX, but generated** | Time intelligence — YoY, MTD, rolling 12. These are functions of filter context rather than properties of the metric, so DAX is the right engine. They are emitted from the registry (`time_comparisons:`) using the fact's own date binding, so nobody hand-picks a date column. |
| **Registry only** | Anything that changes what the number means: filters, grain, aggregation, base model, cost pool, promise basis. |

**What enforces it.** `SEMANTIC_FIELDS` and `CONSUMES` in
`scripts/compile_metrics.py` declare which definition fields each renderer
honours, and validation fails if a metric sets a field some computational
target would silently ignore. That check exists because the failure already
happened: the metric-level `filters` list reached only the SQL target, so
Cost Per Order computed \$1,560.78 in the warehouse and \$1,830.79 in the
generated DAX — a 17.3% divergence, in a file that headed itself "the dashboard
and the database cannot drift apart". 511 shipments with no order reference
were excluded by one engine and included by the other.

**What proves it.** `scripts/test_metric_parity.py` reconciles every metric
between its pre-aggregated model and its base fact on each build. That is rung
L3 of five:

| Rung | Catches | Status |
|---|---|---|
| L1 · field-consumption assert | silently dropped fields | in `validate()` |
| L2 · structured filters | translation bugs, by construction | in the schema |
| L3 · `mtr_*` vs base fact | re-aggregation and aggregation errors | runs on every build |
| L4 · execute the DAX and diff | everything else | queries generated, needs a Power BI runtime |
| L5 · one engine (Cube / dbt SL) | drift impossible — no renderers | open question 5 |

L4 is the only rung that proves the two *engines* agree rather than that the
two *definitions* agree. Its queries are generated into
`exports/powerbi/parity/` with the warehouse's answer beside each, so the gate
exists the day someone first opens the model. It is a manual thirty-minute step
per release, named in [powerbi_model.md](powerbi_model.md).

**Cost of a new frontend.** One renderer, once — roughly 200 lines, the size of
`target_cube`. Metric authors never touch it. The AI path needs no renderer at
all, because it reads `exports/semantic/metric_registry.json`. That is what
"swap the frontend" buys, stated honestly: a one-time engineering cost
amortised across every metric, not a config flag.

---

## 6. The AI use case

The plan's secondary goal: an agent should be able to answer "what was on-time
delivery for the Reno site last quarter" without being handed SQL or a data
dictionary. `scripts/ask_metric.py` demonstrates that it can, reading only
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
date, customer, site, carrier"*. The registry knows which dimensions each
metric supports, so an agent cannot silently produce a figure from a join that
does not hold — which is exactly what happens when an agent is handed nine wide
tables and left to infer the relationships.

**It reports blocked metrics as blocked.** Asked for Return Rate, it returns no
number and instead explains that no returns object exists in any source, lists
the five checks that establish it, and states what the business would have to
supply. This is the single most valuable thing the registry does for an agent.
A model that cannot see the gap will fill it with something plausible.

**It carries the caveats with the number.** The DSO proxy arrives labelled
provisional, with "publish alongside `unsettled_invoice_rate`" attached. Cost
Per Order arrives flagged as not re-aggregatable. The warnings travel with the
figure instead of living in a document nobody opens.

**It knows which dashboards a metric is on** — read from the seed map, not from
the metric definition, which is the same separation the whole design rests on.

If Cube is chosen in Phase 8, this script is replaced by Cube's REST API and
the registry compiles to Cube schema instead. The contract an agent consumes
does not change.

---

## 7. Data quality: four warnings, on purpose

Relationship tests on the README's dashed lines are set to `warn` with a
documented threshold and a note saying what a change would mean. Deleting them
would hide the finding; erroring on them would make the build permanently red.

| Warning | Rows | What it means |
|---|---|---|
| `pangea.shipment.reference_number` → `SORDER` | 264 | Customer POs in the reference field. Errors above 600. |
| `netstock.item_location` → `ITMMASTER` | 35 | Items planned but not mastered. Errors above 50. |
| Paycom `work_email` uniqueness | 12 | Duplicate people in the roster. Errors above 15. |
| `paycom.gl_mapping` → `GACCENTRYD` | 11 | **The README draws this as a solid line. It is not one.** Payroll accounts 50100–50140 and 21500–21700 do not exist in the GL, which only holds 11100, 22300 and 41000. Errors above 11. |

That last one is a finding, not a nuisance: payroll is not posted to the general
ledger in this extract, which is part of why a fully-loaded Cost Per Order is
not computable.

### Reconciliation

`fct_invoice_line.line_net_amount_usd` sums to **218,855,425.75** and reconciles
to GL account 41000 (**218,855,425.84**) **within \$0.09** — about four parts
per billion. The residual is FX rounding: the fact converts each line with a
`decimal(18,6)` rate against a `decimal(18,4)` amount, while the GL carries an
amount already converted at posting.

That is asserted rather than claimed:
`tests/assert_invoice_lines_reconcile_to_gl_revenue.sql` fails above a \$1.00
tolerance — comfortably above the residual, comfortably below anything that
would be a real difference. It is the one figure in the deck a CFO will check,
which is why it is a test and not a sentence.

Every metric reproduces its Phase 0 audit figure:

| Metric | Value |
|---|---|
| On-Time Delivery | 75.6% |
| Cost Per Shipment | $1,564.18 |
| Cost Per Order | $1,560.78 |
| DSO (days-to-pay proxy) | 48.2 days |
| Unsettled Invoice Rate | 13.7% |
| Order Reference Coverage | 85.4% |
| Unmatched CRM Customers | 11.9% |

---

## 8. What is generated and what is hand-written

Roughly 70% of the SQL in this project is generated. That is a deliberate
choice and it is worth being explicit about, because generated code that
nobody can regenerate is worse than hand-written code.

| Generated by | Output | Regenerate with |
|---|---|---|
| `scripts/generate_staging.py` | 46 staging models | edit the column spec, re-run |
| `scripts/compile_metrics.py` | 7 metric models, dbt semantic models, DAX, TMDL, Cube, JSON, catalogue, registry seed | edit the metric YAML, re-run |
| `scripts/generate_process_views.py` | 9 process views | edit the seed map, re-run |
| `scripts/export_powerbi.py` | Parquet + the full TMDL model | re-run |
| `scripts/freeze_schema_contract.py` | the pinned source schema contract | re-run, then **review** |

All of them run in order via `scripts/regenerate.py`.

The generators have an ordering dependency - editing a metric definition
changes the compiled registry, which changes the process views - so
`scripts/regenerate.py` runs them in order and `--check` fails if regeneration
moves the working tree. That is the CI guard, and it exists because the failure
already happened once: a blocked reason was edited, the metric artefacts were
recompiled, the process views were not, and `mart_s2p.sql` sat in the repo for
a commit carrying text that no longer matched its definition. Nothing broke,
because a stale generated file is still valid SQL. That is what makes it
dangerous.

### What actually reads each compiled target

Five targets is a count. Which of them anything executes is the more revealing
question, and the answer is not evenly distributed:

| Target | Consumed by | Executed |
|---|---|---|
| DAX / TMDL | the Power BI model — the deliverable | never opened |
| `mtr_*` SQL | `ask_metric.py`, the `mart_*` views, the parity test | yes |
| JSON registry | `ask_metric.py` | yes |
| `metric_registry` seed | the `mart_*` views, dbt referential tests | yes |
| MetricFlow | nothing — parses and validates only | never queried |
| Cube schema | nothing — no instance exists | never run |

One split inside that deserves stating, because Phase 5 naming the nine process
views as a deliverable invites the opposite assumption. `export_powerbi.py`
writes Parquet for all 30 tables, including the seven `mtr_*` and nine `mart_*`
ones — but **the generated TMDL loads only the twelve core tables**. The
dashboard composes its tiles from `process_metric_map` and computes every value
in DAX from the star. The metric and process tables ship beside the model and
are not read by it.

That is the right architecture, for the reasons in §4a — but it was only said
in a code comment, and a docs reader would have concluded the opposite.

**Hand-written and staying that way**: the 8 intermediate models, the 9 core
models, all model YAML, the seeds, and the singular tests. That is where the
thinking is. Everything generated is mechanical, and mechanical code written by
hand is where inconsistency creeps in precisely because nobody reviews the
forty-third near-identical file.

Every generated file carries a banner naming the script and the input.

---

## 9. What was not built, and why

- **The other five conformed dimensions** — `dim_supplier`, `dim_employee`,
  `dim_gl_account`, `dim_deal_stage`, and the seven remaining facts. No active
  metric needs them. They are named and grained in the plan so the decision is
  made once; building them now would be building unread code.
- **The other six process views are empty by design**, not by omission. Six
  processes have no metrics.
- **Two intermediate models are built but unconsumed** — `int_employee_xref`
  and `int_deal_erp_order_number`. Nothing in `marts/core/` reads them, because
  no active metric needs an employee or a CRM deal. They are kept because their
  findings are governance results in their own right (150 Paycom rows describe
  138 people; 96 recoverable deals become 145) and because the resolution is
  then done and tested for the first H2R, P2C or M2O metric that needs it.
  Cost to carry: two tables, 217 rows. The DAG in
  [data_model.md](data_model.md#44-entity-resolution-path) shows the dead ends
  explicitly rather than leaving them to be found.
- **The other 29 metrics** (nine dashboards × four slots, minus seven defined).
  Undefined and explicitly out of scope. Inventing them would be the single
  most expensive mistake available here.
- **A running Cube instance or an opened Power BI file.** Both artefacts
  generate; neither has been executed in this environment, and the docs say so
  rather than implying otherwise.
- **Slowly changing dimensions.** Every conformed dimension is Type 1, so two
  years of history carry today's attributes. Snapshots on the three sources
  that would feed a Type 2 dimension now run and accumulate, but nothing
  consumes them and no dimension is historised. This is the one gap that gets
  more expensive with time rather than staying flat — see open question 11.
- **Role-playing date relationships.** `delivered_date_key` (3,381 populated),
  `payment_date_key` (8,432) and `requested_delivery_date_key` (11,575) exist
  on the facts, carry no `relationships` test, and have no Power BI
  relationship. "DSO by settlement month" and "on-time by delivery month" are
  the two most obvious follow-ups on those dashboards, and neither is
  answerable in the exported model. Each needs an inactive relationship plus a
  `USERELATIONSHIP` variant measure.
- **Incremental materialisation.** Everything is a full refresh. At 233,000
  rows that is correct. The ingestion asymmetry that will drive the real
  decision is already documented: X3 has `UPDTICK_0`, HubSpot has
  `hs_lastmodifieddate`, Paycom has nothing and is full-refresh-only.

### Declared but not built

Five things the design commits to in writing and does not yet do. Each is
declared where someone would look for it, so it gets built rather than
rediscovered — but declaring is not doing, and the difference is worth listing
in one place.

| What | Declared where | Blocked on |
|---|---|---|
| **Delete reconciliation.** Merge disposition never removes a row, so a row hard-deleted upstream persists forever. | `TableSpec.reconcile_keys` — `weekly` on all 20 merge tables, shown as a `deletes` column in `run_ingestion.py --explain` | Nothing. It is a periodic key diff against the source, and it is the largest single gap in the ingestion design. |
| **The FX company-currency restriction.** `int_fx_rate` derives a document-to-*company*-currency rate and publishes it as a reporting-currency rate. | `COMPANY.CUR_0` on the extraction spec; `tests/assert_fx_rate_is_not_identity_for_foreign_currency.sql` catches the symptom meanwhile | The column does not exist in the mock. Open question 10. |
| **L4 parity — executing the generated DAX.** The only rung that proves the two *engines* agree rather than the two *definitions*. | Queries generated into `exports/powerbi/parity/` with expected values; named as a release step in [powerbi_model.md](powerbi_model.md) | A Power BI runtime, which this environment does not have. |
| **Landing archive compaction.** The projection rescans the whole archive every run, so it degrades with archive *age* rather than source volume. | [ingestion.md §8](ingestion.md) | Nothing — it is correct until the archive is large, and premature until then. |
| **Time-comparison measures.** `time_comparisons:` compiles YoY, MTD, YTD and rolling-12 from the metric's own date binding. | The registry schema and the dax/tmdl targets; validated against the base model's date binding | Nothing. No metric sets it, which is the intended state until a dashboard needs one. Phase 8. |

One check degrades rather than failing: column existence needs
`target/catalog.json`, so on a clean checkout the compiler prints a note saying
the check did not run. A silent skip would mean "Registry OK" without the
strongest validation having happened.

---

## 10. The thirteen open questions

Full detail in [open_questions.md](open_questions.md). Twelve are config
changes whenever the business answers. One is not, and it is the only entry
here with a deadline attached.

Summary:

| # | Question | Assumed | Encoded as |
|---|---|---|---|
| 1 | On-Time Delivery promise basis | Carrier promise | `var: otd_promise_basis` |
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

None of them blocked the build, and every one is visible in an artefact rather
than in someone's memory.

**Twelve are reversible whenever the business answers. Question 11 is not.**
A Type 2 dimension can only be built forward from its first snapshot, and no
source in the estate carries effective dating, so deferring that decision does
not defer the cost — it deletes the history the decision would need. Snapshots
on the three candidate sources now run and accumulate against that day, which
costs one command in the schedule and buys the option.
