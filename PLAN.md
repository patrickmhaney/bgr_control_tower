# POC Plan: Process Performance Analytical Data Model

You are building a proof of concept for an analytical data model. Read this whole
document before writing code. Where it says **STOP AND ASK**, do not guess —
surface the question and wait.

---

## 1. Context

### What exists in this working directory

| File | What it is |
|---|---|
| `mock_sources.duckdb` | Five mock source schemas, ~233k rows, Jul 2024 – Aug 2026 |
| `README.md` | **Read this first.** Source fidelity, the cross-system join map, and 14 deliberate data-quality landmines |
| `generate_mock_sources.py` | Seeded generator |
| `schema.sql` | Portable DDL if we move off DuckDB |

Source schemas: `sage_x3` (ERP), `hubspot` (CRM), `paycom` (payroll),
`netstock` (forecasting), `pangea` (shipments — product identity unconfirmed).

These are mocks standing in for real systems. Model as if they were real. The
landmines in `README.md` are all things that exist in the actual sources.

### The business goal

Nine Power BI dashboards, one per business process, each driven by four metrics.
Seven metrics are currently defined; the rest are undefined and **out of scope
for this POC**. Do not invent them.

Two design constraints follow from that:

1. **Optimize for cheap metric addition.** Adding a metric later should require
   a metric definition and possibly one fact model — nothing else.
2. **Metrics are not owned by processes.** The same metric may appear on several
   dashboards. Define metrics once, independently, and map them to processes
   through a separate many-to-many relationship.

### Secondary goals, in scope for the design

- **Semantic layer** for AI use cases — an agent should be able to answer
  "what was on-time delivery for the Reno site last quarter" without being
  handed SQL or a data dictionary.
- **Governance** — every metric has exactly one definition, an owner, a stated
  grain, and traceable lineage to source columns.

---

## 2. The process/metric matrix

Nine processes, referred to **by acronym only**. Their expansions are not yet
confirmed by the business; do not guess at them, do not write them anywhere in
code or docs, and do not let them influence modeling decisions.

`P2C` · `O2C` · `S2P` · `F2P` · `I2D` · `R2P` · `H2R` · `I2S` · `M2O`

Seven defined metrics, assignment confirmed:

| Metric | Process | Slot |
|---|---|---|
| DSO | O2C | M1 |
| Return Rate | O2C | M2 |
| Cost Per Order | O2C | M3 |
| Match Rate | S2P | M1 |
| Inventory Accuracy | I2D | M1 |
| On-Time Delivery | I2D | M2 |
| Cost Per Shipment | I2D | M3 |

Encode this as a seed, `seeds/process_metric_map.csv`, with columns
`process_code, metric_name, slot, display_order`. This is the many-to-many join
between the metric registry and the dashboards — a metric appearing on two
dashboards is two rows here, not two definitions.

Six processes currently have no metrics. That is fine. They exist in the map as
empty and the architecture must tolerate that.

---

## 3. Architecture

### Recommendation

One conformed dimensional core. Nine thin presentation views on top. Metrics
defined once in a semantic layer that sits between them.

```
  source systems (DuckDB schemas)
        │
  ┌─────▼──────────────────────────────────────────┐
  │ staging/     1:1 with source tables            │  cleaning only:
  │              stg_sage_x3__sorderq, etc.        │  trim, cast, sentinel→null,
  └─────┬──────────────────────────────────────────┘  rename, decode local menus
        │
  ┌─────▼──────────────────────────────────────────┐
  │ intermediate/  crosswalks + entity resolution   │  int_customer_xref,
  │                                                 │  int_employee_xref
  └─────┬──────────────────────────────────────────┘
        │
  ┌─────▼──────────────────────────────────────────┐
  │ marts/core/   conformed dims + atomic facts     │  ← the data model.
  │               dim_customer, fct_sales_order_line│    process-agnostic.
  └─────┬──────────────────────────────────────────┘
        │
  ┌─────▼──────────────────────────────────────────┐
  │ semantic/     metric registry (YAML)            │  ← one definition per
  │               grain, agg, filters, owner        │    metric. no process
  └─────┬──────────────────────────────────────────┘    ownership.
        │
        ├──── seeds/process_metric_map.csv ────┐
        │                                       │
  ┌─────▼───────────────────┬──────────────────▼───┐
  │ marts/process/          │  AI / agent access   │
  │ 9 flat views, 1 per     │  via the semantic    │
  │ dashboard               │  layer, not the marts│
  └─────────────────────────┴──────────────────────┘
```

### Why this shape

The nine processes overlap on the same underlying facts. Cost Per Order and Cost
Per Shipment both consume Pangea charges. DSO and anything in R2P both consume
invoices and GL entries. All nine need customer, item, site, and date.

Nine independently-built marts would mean nine definitions of "customer", nine
chances for revenue to disagree across dashboards, and nine places to fix every
bug. It also makes the AI use case impossible — an agent handed nine overlapping
wide tables with no entity graph cannot reason about them and will produce
confidently wrong joins.

The nine flat process views still get built. They are *presentation artifacts*
generated from the core, cheap and disposable.

### Power BI implication

Recommend **one shared Power BI semantic model** over the conformed core, with
nine reports against it, rather than nine models. Use perspectives or per-process
display folders to keep each dashboard's surface manageable. A star schema in
import mode also outperforms wide flat tables in VertiPaq — the flat-table
instinct is a holdover from tools that couldn't handle relationships.

Raise this as a recommendation; it has rollout and ownership implications.

### Stack for the POC

- **dbt-core + dbt-duckdb** — staging/marts structure, tests, lineage, generated
  docs. The dbt project *is* the governance artifact.
- **DuckDB** as the engine (already in place).
- **Metric definitions in YAML** alongside the models.
- **Parquet export** to `./exports` for Power BI import. Don't fight
  DuckDB→Power BI connectivity during a POC.

```bash
pip install dbt-core dbt-duckdb duckdb
```

### The semantic layer decision

**STOP AND ASK** before committing. Present these with tradeoffs:

1. **dbt semantic models / MetricFlow** — metrics live next to the models,
   strong lineage. Local `mf` CLI works with dbt-core; the hosted Semantic Layer
   API requires dbt Cloud. Best governance story.
2. **Cube** — open source, REST/SQL API that AI agents consume well, runs
   anywhere including Azure. Best AI story, a second system to operate.
3. **Power BI semantic model (TMDL) as source of truth** — no new
   infrastructure, but metrics become invisible outside Power BI, which kills the
   AI use case.

Default recommendation is (1) for the POC, with metric YAML written
tool-neutrally enough that generating Cube schema or TMDL later is a
transformation, not a rewrite.

**Spike this early.** The high-value, high-risk idea is generating both the SQL
and the Power BI DAX/TMDL measures from one metric definition. If that doesn't
work cleanly, we fall back to hand-maintained DAX referencing the YAML as
documentation — worse but survivable. Find out in Phase 3, not Phase 6.

---

## 4. Modeling spec

### Metric registry

Each metric is one YAML entry. Required fields:

```yaml
- name: on_time_delivery_rate
  label: On-Time Delivery
  status: active            # active | blocked | provisional
  description: <business-language definition, one paragraph>
  grain: <what one row of the denominator is>
  numerator: <expression>
  denominator: <expression>
  base_model: fct_shipment
  filters: [...]
  dimensions: [date, site, customer, carrier]
  owner: <TBD - ask>
  lineage_notes: <source columns and any assumptions made>
  blocked_reason: null
```

No process field. Process association lives in the seed map.

Blocked metrics get an entry with `status: blocked`, a populated
`blocked_reason`, and no SQL. They appear in the registry and in generated docs
so the gap is visible, and they cost nothing until the data arrives.

### Conformed dimensions

| Model | Notes |
|---|---|
| `dim_date` | Generated. Include fiscal periods — **ASK** what the fiscal calendar is. |
| `dim_item` | From `ITMMASTER`. Decode `ITMSTA_0` via `APLSTD`. |
| `dim_customer` | **Conformed across X3 and HubSpot.** See entity resolution below. |
| `dim_supplier` | `BPSUPPLIER` + `netstock.supplier`. Clean join on supplier_code. |
| `dim_site` | `FACILITY`, plus the Paycom `location_code` crosswalk. |
| `dim_employee` | **Conformed across X3 `REPRESENT` and Paycom `employee`.** |
| `dim_carrier` | `pangea.carrier`. |
| `dim_gl_account` | Derive from `GACCENTRYD` + `paycom.gl_mapping`. |
| `dim_deal_stage` | `hubspot.pipeline_stage`. |

### Atomic facts

Grain must be stated explicitly in every model's YAML description.

| Model | Grain |
|---|---|
| `fct_sales_order_line` | `SOHNUM_0` + `SOPLIN_0` (join SORDERQ to SORDERP) |
| `fct_invoice_line` | `NUM_0` + `SIDLIN_0` |
| `fct_inventory_movement` | `STOJOU.ROWID` |
| `fct_inventory_balance` | Item × site × lot, periodic snapshot |
| `fct_purchase_order_line` | `POHNUM_0` + `POPLIN_0` |
| `fct_gl_entry_line` | `NUM_0` + `LIN_0` |
| `fct_shipment` | `shipment_id` |
| `fct_shipment_event` | `shipment_id` + `event_seq` |
| `fct_forecast` | Item × location × period, snapshot with `last_sync_at` |
| `fct_deal_stage_change` | `deal_id` + stage transition |
| `fct_payroll_earning` | `check_id` + `earning_code` |

Build only the facts the active metrics need (see Phase 3). The rest are listed
so the naming and grain decisions are made once, not rediscovered later.

### Entity resolution — explicit and inspectable

There is **no shared key** between HubSpot companies and X3 customers, or between
Paycom employees and X3 sales reps. Do not bury matching logic inside a dimension.

Build `int_customer_xref` and `int_employee_xref` as first-class models emitting
one row per match candidate with `match_method` and `confidence` columns.
`dim_customer` then selects from the xref under a documented survivorship rule
(suggested starting point: X3 wins on financial attributes, HubSpot wins on
firmographics).

Expose the unmatched rate as a data quality metric. The business needs to see
that number — it's a governance finding, not an engineering embarrassment.

---

## 5. Phases

### Phase 0 — Metric feasibility audit

Before any modeling, determine whether each of the seven defined metrics can be
computed from available source data. Write findings to
`docs/metric_feasibility.md`. **Document the gaps and move on — do not solve
them, do not invent source objects, do not extend the mock generator.**

Preliminary read — **verify each, don't trust it**:

| Metric | Status | Note |
|---|---|---|
| Cost Per Shipment | ✅ computable | `shipment.total_cost_usd` deliberately disagrees with `sum(charge.amount_usd)`. Pick one, document why. |
| On-Time Delivery | ✅ computable | Against *which* promise? `pangea.estimated_delivery_date` (carrier) vs `SORDERQ.DEMDLVDAT_0` (customer request) give materially different answers. Decision needed. |
| DSO | ⚠️ proxy only | No cash application data. `SINVOICEV.PAYDAT_0` supports a days-to-pay proxy, which is not textbook DSO. |
| Cost Per Order | ⚠️ needs a rule | Computable only with an allocation basis. Which cost pool — fulfillment only, or fully loaded? |
| Return Rate | ❌ blocked | No returns object exists in any source. |
| Match Rate | ❌ blocked | No supplier invoice table. Three-way match needs PO + receipt + invoice; only the first two exist. |
| Inventory Accuracy | ❌ blocked | No cycle count data. `STOJOU` adjustments (`TRSTYP_0 = 3`) are a weak proxy at best. |

Three of seven metrics are blocked outright and two more need a business
decision. **This is the most important early finding on the project.** Register
the blocked ones with `status: blocked` and surface them in the docs; the client
will resolve the source gaps separately.

### Phase 1 — Project scaffold

dbt project initialized against `mock_sources.duckdb`, folder structure per §3,
`dbt run` succeeds on an empty model set, `dbt docs generate` works. Commit.

### Phase 2 — Staging layer

One model per source table. Cleaning only, no business logic. Every landmine in
`README.md` handled here and nowhere else:

- `trim()` all X3 CHAR-padded keys
- `1753-01-01` → `null`
- Cast HubSpot string properties
- Parse Paycom `MM/DD/YYYY` strings
- Decode local menus via `APLSTD`
- Flag (don't filter) `archived` HubSpot records — let the mart decide

Add dbt tests: `not_null` and `unique` on every declared grain, `relationships`
tests on every join in the README's join map. **Expect the tests on the dashed
lines to fail.** That is the point — set them to `warn` with a documented
threshold rather than deleting them.

### Phase 3 — Core model + semantic layer spike

Build `dim_date`, `dim_item`, `dim_site`, `dim_customer` (with xref),
`dim_carrier`, and the facts the four computable/proxy metrics need:
`fct_shipment`, `fct_shipment_event`, `fct_sales_order_line`, `fct_invoice_line`.

In parallel, spike metric YAML → SQL and metric YAML → DAX/TMDL generation on
**one** metric (Cost Per Shipment, the simplest). Report on feasibility before
building the rest.

### Phase 4 — Metric registry

Populate all seven metrics. Four with definitions, three as `status: blocked`.
Build the seed map. Verify a metric can be pointed at two processes without
duplicating its definition — that's the property the whole design turns on, so
test it explicitly even though no current metric needs it.

### Phase 5 — Process views

Build flat presentation views for O2C, S2P, and I2D. Prove they are generated
from the core and the seed map, not hand-written. S2P will be nearly empty
(its only metric is blocked) — that's a valid test of the empty case.

### Phase 6 — Power BI slice

Export Parquet to `./exports`. Build one dashboard: I2D, which has On-Time
Delivery computable and Cost Per Shipment computable. Document the semantic model
structure and the measure-generation approach.

### Phase 7 — Write-up

`docs/architecture.md`: the model, a metric-addition runbook ("here is exactly
what you do to add a metric"), the entity resolution approach and its unmatched
rates, and the open questions list.

---

## 6. Conventions

- Naming: `stg_<source>__<table>`, `int_<subject>_<verb>`, `dim_<entity>`,
  `fct_<event>`, `mart_<process_acronym>`.
- Use process acronyms verbatim. Never expand them.
- Every model gets a YAML description stating its **grain** in one sentence.
- No business logic above staging that isn't traceable to a metric definition.
- SQL: CTEs over subqueries, one CTE per logical step, no `SELECT *` past staging.
- Commit at the end of each phase with a message describing what was proven.

---

## 7. Things to raise, not guess

Collect in `docs/open_questions.md`:

1. On-Time Delivery: carrier promise date or customer request date?
2. DSO: true AR-based, or days-to-pay proxy?
3. Cost Per Order: which cost pool, and what allocation basis?
4. Fiscal calendar definition.
5. Semantic layer tool choice (§3).
6. One shared Power BI semantic model vs nine (§3).
7. Customer survivorship rule between X3 and HubSpot.
8. Metric ownership — who signs off on each definition?
9. What is Pangea, actually? The shipment schema is inferred from a guess.
10. Currency: the mock has USD and CAD. Single or multi-currency reporting, and
    if multi, whose FX rates as of what date?

Do not block on these — proceed with the documented assumption and flag it. But
do not silently pick one.
