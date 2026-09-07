# Power BI: the I2D slice

Phase 6 builds one dashboard end to end — I2D, the only process whose metrics
are both computable — and documents the semantic model structure and the
measure-generation approach behind it.

---

## Recommendation: one shared semantic model, nine reports

**Not nine models.** This has rollout and ownership implications, so it is
raised as a recommendation rather than assumed.

### Why

The nine processes overlap heavily on the same facts and the same dimensions.
Cost Per Order and Cost Per Shipment both consume Pangea charges. DSO and
anything in R2P both consume invoices. All nine need customer, item, site and
date.

Nine independent models would mean:

- Nine definitions of "customer", each free to drift.
- Nine chances for revenue to disagree between dashboards, with no mechanism
  that would detect it.
- Nine places to apply every bug fix.
- Nine refresh schedules against the same source data.

One shared model means "the same metric shows the same number on two
dashboards" is structurally guaranteed rather than maintained by discipline.
`scripts/test_metric_reuse.py` asserts that property at the warehouse level;
one semantic model is what preserves it in Power BI.

### Performance

A star schema in import mode outperforms wide flat tables in VertiPaq. Wide
tables repeat every dimension attribute on every fact row, which destroys the
dictionary compression VertiPaq depends on. The flat-table instinct is a
holdover from tools that could not handle relationships — Power BI can.

Model size here is trivial: the largest fact is 24,504 rows and the whole
Parquet export is under 1 MB. Nothing about this decision is performance-driven
at POC scale; it is about correctness and maintenance cost, and it will still
be right at 400,000 orders.

### Managing surface area

The objection to one model is that a report author for I2D should not have to
scroll past twenty O2C fields. Two mechanisms:

- **Perspectives** — a named subset of tables, columns and measures per
  process. Requires Tabular Editor or a Premium/Fabric workspace to author.
- **Display folders** — measures are already emitted into
  `Metrics` and `Metrics\Provisional` folders by the generator, and the folder
  path comes from the metric's status. Adding a per-process folder is a
  one-line change to `measure_lines()` in `scripts/export_powerbi.py`.

### What the client has to decide

This is an ownership question, not a technical one. One model means one
deployment pipeline, one refresh schedule, one set of row-level security rules,
and one team that approves changes to it. If the nine dashboards have nine
owners who each want to ship independently, that tension has to be resolved
before the model is built. Open question 6.

---

## The model

### Tables

Exported to `exports/parquet/` and referenced by the generated TMDL.

| Table | Role | Rows |
|---|---|---|
| `dim_date` | Conformed calendar, 2024-2027 | 1,461 |
| `dim_customer` | Conformed across X3 and HubSpot | 251 |
| `dim_site` | Conformed across X3, Paycom, Netstock | 3 |
| `dim_item` | X3 master with Netstock planning attributes | 420 |
| `dim_carrier` | Pangea carriers | 7 |
| `fct_shipment` | Shipment header | 3,509 |
| `fct_shipment_event` | Tracking events | 24,504 |
| `fct_sales_order_line` | Order lines | 11,575 |
| `fct_invoice_line` | Invoice lines | 9,767 |
| `metric_registry` | Metric metadata: status, owner, caveats | 10 |
| `process_metric_map` | Which metric appears on which dashboard | 7 |
| `process` | The nine processes | 9 |

The last three are unusual on a Power BI model and they are there deliberately.
They let a report show *why* a tile is empty — "Inventory Accuracy is blocked:
no cycle count data exists" — instead of showing a blank card that reads as
zero. They also let a dashboard display each metric's owner and status without
a second source of truth.

### Relationships

Sixteen, all single-direction, all many-to-one from fact to dimension.

```
                          dim_date
                        (date_key)
                             ▲
          ┌──────────────────┼──────────────────┐
          │                  │                  │
   fct_shipment      fct_sales_order_line   fct_invoice_line
   ship_date_key     order_date_key         invoice_date_key
          │                  │                  │
          ├──► dim_customer (customer_key) ◄────┤
          ├──► dim_site     (site_code)    ◄────┤
          ├──► dim_carrier  (carrier_scac)      │
          │                  └──► dim_item ◄────┘
          │                       (item_code)
          ▼
   fct_shipment_event
```

Single-direction cross-filtering throughout. Bidirectional filtering on a star
this shape creates ambiguous filter paths as soon as a second fact is added,
and the resulting numbers are wrong in ways that are extremely hard to
diagnose. Every one of these relationships is already asserted by a dbt
`relationships` test, so the model is not relying on Power BI to discover a
join that does not hold.

**What the sixteen do not cover: secondary dates.** They are the *primary* date
on each fact plus the non-date dimensions. Three role-playing date keys exist
on the facts and are unrelated in the model:

| Key | Populated | The question it would answer |
|---|---|---|
| `delivered_date_key` | 3,381 | on-time delivery by *delivery* month rather than ship month |
| `payment_date_key` | 8,432 | the DSO proxy by *settlement* month |
| `requested_delivery_date_key` | 11,575 | order lines by the date the customer asked for |

Those are the two or three most obvious follow-ups a user will have on these
dashboards, and none is answerable in the exported model. Out of POC scope
deliberately — each needs an inactive relationship plus a `USERELATIONSHIP`
variant measure, which is a decision about how many measures a report author
should see rather than a technical obstacle.

**Every dimension carries an UNKNOWN member** and every fact coalesces its
foreign keys to it, so an unresolved key lands on a labelled row rather than a
blank one. In Power BI a blank dimension row reads to a user as a real member;
"Unresolved" does not. Nothing is unresolved today.

`discourageImplicitMeasures` is set. Every number on a report should come from
a defined measure, not from a column someone dragged onto a visual and Power BI
decided to sum.

---

## Measures: generated, never written

All seven active and provisional metrics become DAX measures. Zero are
hand-written. The chain:

```
semantic/metrics/on_time_delivery_rate.yml
        │
        │  scripts/compile_metrics.py
        ├────────────────────────────► models/marts/metrics/mtr_*.sql   (warehouse)
        │
        │  scripts/export_powerbi.py, importing the same generator
        └────────────────────────────► exports/powerbi/model/definition/ (Power BI)
```

Because both sides derive from the same file, a change to a metric cannot land
in one and not the other. That is the property that makes "one definition per
metric" true in practice rather than aspirationally.

Each generated measure carries annotations back to its definition:

```
measure 'On-Time Delivery' = DIVIDE(
    CALCULATE(COUNTA(fct_shipment[shipment_id]), fct_shipment[is_on_time] = TRUE()),
    CALCULATE(COUNTA(fct_shipment[shipment_id]), NOT ISBLANK(fct_shipment[is_on_time])))
    formatString: "0.0%"
    displayFolder: Metrics
    /// The share of delivered shipments that arrived on or before the promised...
    annotation MetricName = on_time_delivery_rate
    annotation MetricStatus = active
    annotation MetricOwner = TBD
    annotation MetricReaggregatable = true
    annotation DefinitionFile = semantic/metrics/on_time_delivery_rate.yml
```

An analyst who wonders where a number comes from can read the definition file
path out of the model.

### The one measure that needed special handling

Cost Per Order has a distinct-count denominator. Its DAX uses
`DISTINCTCOUNT(fct_shipment[sales_order_number])` against the fact rather than
summing a pre-aggregate, so it stays correct at every grain a user drills to.
The annotation `MetricReaggregatable = false` records why.

---

## The I2D dashboard

Three of I2D's four slots are filled; the fourth is undefined and out of scope.

| Slot | Metric | Status | Value |
|---|---|---|---|
| M1 | Inventory Accuracy | **blocked** | — no cycle count data exists |
| M2 | On-Time Delivery | active | **75.6%** |
| M3 | Cost Per Shipment | active | **$1,564.18** |
| M4 | — | undefined | out of scope for the POC |

### Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  I2D                              [Date] [Site] [Carrier] [Mode] │
├────────────────┬────────────────┬────────────────────────────────┤
│ On-Time        │ Cost Per       │ Inventory Accuracy             │
│ Delivery       │ Shipment       │                                │
│                │                │ ┌────────────────────────────┐ │
│    75.6%       │   $1,564.18    │ │ BLOCKED                    │ │
│    ▲ 4.9 pts   │   ▲ $110.86    │ │ No cycle count data exists │ │
│    better      │   worse        │ │ in any source system.      │ │
│    vs prior Q  │   vs prior Q   │ │ Owner: TBD                 │ │
│  3,381 of      │  3,509         │ └────────────────────────────┘ │
│  3,509 deliv.  │  shipments     │                                │
├────────────────┴────────────────┴────────────────────────────────┤
│  On-Time Delivery by quarter        Cost per shipment by quarter │
│  ▁▃▁▁▂▁▅▁▄  73.1% → 81.3%          ▅▃▂▂▄▃▅▂▅  $1,509 → $1,631   │
├──────────────────────────────────────┬───────────────────────────┤
│  Carrier performance                 │  Cost composition         │
│  ┌────────────────┬──────┬────────┐  │  Freight        4,669,273 │
│  │ Old Dominion   │78.3% │ $1,603 │  │  Fuel             547,955 │
│  │ C.H. Robinson  │77.8% │ $1,406 │  │  Detention         91,214 │
│  │ UPS            │75.5% │ $1,530 │  │  Liftgate          90,436 │
│  │ Saia LTL       │75.4% │ $1,596 │  │  Residential       89,831 │
│  │ Purolator      │74.9% │ $1,533 │  │                           │
│  │ XPO Logistics  │73.9% │ $1,620 │  │  Header cost is 9.9%      │
│  │ FedEx Ground   │73.6% │ $1,656 │  │  higher than these lines  │
│  └────────────────┴──────┴────────┘  │  — see cost_variance_usd  │
├──────────────────────────────────────┴───────────────────────────┤
│  ⚠ 511 of 3,509 shipments (14.6%) do not resolve to an X3 order  │
│  ⚠ 298 shipments have out-of-sequence carrier scans              │
└──────────────────────────────────────────────────────────────────┘
```

Three things about that layout are deliberate:

**The blocked tile is a tile.** Inventory Accuracy occupies its slot and states
why it is empty, sourced from `metric_registry[blocked_reason]`. A missing tile
gets forgotten; a tile that says "no cycle count data exists in any source
system" gets escalated.

**Coverage warnings are on the dashboard, not in an appendix.** 14.6% of
shipments cannot be tied to an order, which bounds what any order-level cut of
this data can say. A user who filters by customer should be able to see that
number without asking.

**Carrier performance shows cost and on-time together.** The cheapest carrier
in the set (C.H. Robinson, $1,406) is also the second most reliable (77.8%),
and the most expensive (FedEx Ground, $1,656) is the least (73.6%). Splitting
those into two visuals hides the only interesting thing in the data.

### Measured detail behind the tiles

On-time and cost by carrier:

| Carrier | Mode | Shipments | On-time | Cost/shipment |
|---|---|---|---|---|
| Old Dominion | LTL | 472 | 78.3% | $1,603.17 |
| C.H. Robinson | TL | 484 | 77.8% | $1,405.65 |
| UPS | PARCEL | 496 | 75.5% | $1,530.30 |
| Saia LTL Freight | LTL | 518 | 75.4% | $1,595.91 |
| Purolator | PARCEL | 526 | 74.9% | $1,533.01 |
| XPO Logistics | LTL | 497 | 73.9% | $1,620.39 |
| FedEx Ground | PARCEL | 516 | 73.6% | $1,655.55 |

By fiscal quarter (fiscal = calendar, assumed — open question 4):

| Quarter | Shipments | On-time | Cost/shipment |
|---|---|---|---|
| FY2024-Q3 | 405 | 74.2% | $1,611.83 |
| FY2024-Q4 | 270 | 79.6% | $1,556.04 |
| FY2025-Q1 | 291 | 74.7% | $1,512.93 |
| FY2025-Q2 | 457 | 73.1% | $1,512.65 |
| FY2025-Q3 | 518 | 74.9% | $1,587.43 |
| FY2025-Q4 | 326 | 73.6% | $1,557.04 |
| FY2026-Q1 | 360 | 81.3% | $1,631.17 |
| FY2026-Q2 | 559 | 73.6% | $1,509.45 |
| FY2026-Q3 | 323 | 78.5% | $1,620.31 |

Both series are noise around a flat trend, which is what mock data should look
like. Do not read a story into the FY2026-Q1 spike.

---

## Building it

```bash
dbt build                                    # warehouse
python scripts/export_powerbi.py --process I2D
```

Then in Power BI Desktop:

1. Open the generated model at
   `exports/powerbi/model/definition/` (Power BI Project / `.pbip` format, or
   import via Tabular Editor).
2. Set the `ExportFolder` parameter to the absolute path of
   `exports/parquet/`.
3. Refresh.

Or, to build the model by hand and take only the measures, paste
`exports/powerbi/measures.dax`.

### Release gate: run the parity queries once per release

`exports/powerbi/parity/` holds one DAX query per metric with the warehouse's
answer beside it, generated by `scripts/test_metric_parity.py --write-dax-gate`.
Paste each into Power BI Desktop's DAX Query View and compare.

This is the only check that proves the two *engines* agree rather than that the
two *definitions* agree — the compiler can consume every field correctly and
still differ on semantics, and it already has: DAX `DISTINCTCOUNT` counts BLANK
where SQL `count(distinct)` ignores nulls, which is a one-row difference on any
metric with an unresolved key.

About thirty minutes per release. A mismatch is a compiler bug, not a data
problem — both engines read the same warehouse — so report the metric and both
numbers.

### Status of the generated model

Structurally generated from the live warehouse schema and schema-checked, but
**not opened in Power BI Desktop** — that is not possible in this environment.
Treat it as a validated starting point for the model author. The guarantee it
carries is narrower and more useful than "it opens": no measure in it was typed
by hand, and no column or relationship was transcribed.

---

## Production path

Parquet is a POC decision, not a recommendation. For production:

| Option | When it fits |
|---|---|
| Direct Lake over Fabric OneLake | If the client is on Fabric. The dbt models land as Delta tables and Power BI reads them without import. |
| Import from the warehouse | Snowflake, Databricks, Synapse — whatever the Phase 8 platform decision lands on. Import mode stays right at this data volume. |
| DirectQuery | Only if near-real-time is a stated requirement. It is not, and it would cost the VertiPaq compression this model benefits from. |

The dbt project does not change under any of these. The `dbt-duckdb` adapter is
swapped for another adapter and the models are portable — the SQL uses no
DuckDB-specific syntax except `filter (where ...)` (ANSI, supported by Snowflake
and Postgres) and `arg_min`/`arg_max`/`string_agg` in three intermediate models,
which have direct equivalents everywhere.

---

## Row-level security

Not implemented in the POC and worth flagging early, because it is cheap now
and expensive later.

The natural axes here are site (three values) and sales rep. Both are already
conformed dimensions with clean keys, so RLS would be a filter on `dim_site` or
`dim_customer[primary_rep_code]` propagating through the existing
relationships. One shared model makes this one set of rules; nine models would
make it nine.
