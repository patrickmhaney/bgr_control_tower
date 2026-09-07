# Semantic layer spike — findings

The plan called this out as the high-value, high-risk idea: generate both the
warehouse SQL and the Power BI DAX from one metric definition, and find out in
Phase 3 rather than Phase 6 whether it works.

**It works.** One YAML file per metric now compiles to eight artefacts, and no
measure anywhere in the project is hand-written. The spike also found the one
place where it does not work, which is more useful than a clean pass.

---

## What was built

`scripts/compile_metrics.py` reads three inputs:

| Input | What it holds |
|---|---|
| `semantic/metrics/*.yml` | One file per metric. The definition. |
| `semantic/models.yml` | Which fact each metric sits on, and how that fact reaches each conformed dimension. |
| `semantic/dimensions.yml` | The conformed dimensions a metric may be sliced by. |

and writes eight:

| Target | Output | What consumes it |
|---|---|---|
| `sql` | `models/marts/metrics/mtr_*.sql` | dbt / the warehouse |
| `seed` | `seeds/metric_registry.csv` | dbt tests, and Power BI metadata |
| `dbt_semantic` | `models/semantic/_semantic_models.yml` | MetricFlow |
| `dax` | `exports/powerbi/measures.dax` | a model author pasting measures |
| `tmdl` | `exports/powerbi/tmdl/*.tmdl` | Tabular Editor / Power BI projects |
| `cube` | `exports/cube/model/cubes/*.yml` | Cube, if that route is taken |
| `json` | `exports/semantic/metric_registry.json` | AI agents |
| `docs` | `docs/metric_catalog.md` | people |

`scripts/export_powerbi.py` then assembles a complete TMDL model — tables,
columns, relationships and measures — importing the measure generator rather
than reimplementing it.

## The result on one metric

From this definition:

```yaml
name: on_time_delivery_rate
base_model: fct_shipment
numerator:   {agg: count, expression: shipment_id, filter: is_on_time}
denominator: {agg: count, expression: shipment_id, filter: is_on_time is not null}
dimensions: [date, customer, site, carrier]
```

the compiler produces SQL:

```sql
select
    ship_date_key as date_key, customer_key, site_code, carrier_scac,
    count(shipment_id) filter (where is_on_time) as numerator,
    count(shipment_id) filter (where is_on_time is not null) as denominator
from {{ ref('fct_shipment') }}
group by 1, 2, 3, 4
```

and DAX:

```dax
DIVIDE(
    CALCULATE(COUNTA(fct_shipment[shipment_id]), fct_shipment[is_on_time] = TRUE()),
    CALCULATE(COUNTA(fct_shipment[shipment_id]), NOT ISBLANK(fct_shipment[is_on_time]))
)
```

and Cube, and a dbt semantic model, and a catalogue entry, and a JSON contract.
Both compute 75.6%.

---

## Four things the spike found

### 1. Raw SQL expressions in the registry would have killed it

The plan's sketch has `numerator: <expression>`. A free-text SQL expression
compiles to SQL trivially and to DAX not at all — there is no safe general
translation from SQL to DAX, and a wrong one produces a measure that compiles,
returns a number, and is quietly incorrect.

The registry therefore uses a small structured form instead:

```yaml
numerator:
  agg: sum | count | count_distinct | avg | min | max
  expression: <a column on the base model>
  filter: <optional boolean expression>
```

The cost is that the registry cannot express arbitrary arithmetic. That is the
right trade: every one of the seven defined metrics fits, and the constraint is
what makes multi-target generation safe. When a metric genuinely needs
arithmetic, the arithmetic belongs in the fact model as a column — which is
also where it becomes testable.

The filter dialect is deliberately narrow (boolean column, `IS [NOT] NULL`,
`=`, `IN`) and `dax_filter()` **raises rather than guessing** on anything else.
A translator that silently mistranslates is worse than one that refuses.

### 2. Not every metric is re-aggregatable, and the two targets need different treatment

Cost Per Order has a `count_distinct` denominator. A pre-aggregated SQL model
is correct at the grain it was aggregated to and wrong if you sum it to a
coarser one — an order spanning two sites would be counted twice.

The compiler detects this and handles it differently per target:

- **SQL**: the generated model carries a header warning and the registry
  records `is_reaggregatable: false`.
- **DAX**: `DISTINCTCOUNT` over the fact, which stays correct at every grain.
- **JSON**: the flag is published so an agent knows not to sum it.

This is not a corner case. It is the single most common way a semantic layer
produces confidently wrong numbers, and it only becomes visible when you try to
generate two targets from one definition.

### 3. MetricFlow cannot express one of the metrics

`customer_unmatched_rate` is a point-in-time measure over `dim_customer`, which
has no date. MetricFlow requires an aggregation time dimension on every
measure, so it cannot be represented. The same metric compiles correctly to
DAX and to Cube.

The compiler skips it for that target and names it in the header of the
generated file:

```
# NOT EXPRESSIBLE IN METRICFLOW, and therefore absent below:
#   customer_unmatched_rate - base model dim_customer has no date dimension...
```

**This is the argument for the tool-neutral registry, stated by the tools
themselves.** Had we written the metrics natively in MetricFlow, this metric
would not exist and nobody would know why.

MetricFlow also needs a `metricflow_time_spine` model and a `primary_entity` on
every semantic model. Both are handled — the time spine is a projection of
`dim_date` so the project has one calendar, not two.

### 4. Generating the *whole* Power BI model, not just the measures, is the bigger win

Measures were the risky part and they generate cleanly. But so do the tables,
the columns, the data types, the `summarizeBy` defaults, the display folders,
and the sixteen relationships. `scripts/export_powerbi.py` emits a complete
TMDL model folder.

That matters because the measure is not the only thing that can drift. A
column renamed in dbt and not in Power BI breaks a report; a relationship
pointed at the wrong column produces a plausible wrong number. Generating the
model from the warehouse schema removes both.

---

## Honest limitations

- **The TMDL has not been opened in Power BI Desktop.** That is not possible in
  this environment. It is structurally generated from the live warehouse schema
  and the registry, and it is internally consistent, but it is a validated
  starting point for the model author rather than a signed-off artefact. What
  *is* guaranteed is that no measure was typed by hand.
- **`dax_filter()` covers four filter forms.** It refuses anything else rather
  than guessing. Extending it is a small, local change; the point is that the
  failure mode is a build error rather than a wrong number.
- **Cube schema is generated but Cube has not been run.** Same status as the
  TMDL — it is a migration path, proven to be a transformation rather than a
  rewrite, not a deployed system.
- **`mf` (the MetricFlow CLI) was not exercised.** The semantic models parse
  and validate under `dbt parse`, which is the check that matters for whether
  the generated YAML is well-formed. Querying through `mf` needs
  `dbt-metricflow` installed and is a Phase 8 activity if dbt is chosen.

## Recommendation

Keep the tool-neutral registry regardless of which semantic layer tool is
chosen. It cost roughly 600 lines of Python and it has already paid for itself
twice: once by surfacing the re-aggregation problem, and once by surfacing a
MetricFlow limitation that would otherwise have quietly shaped the metric set.

If the AI use case is real and needs an API, add Cube and point it at the same
registry. If governance inside dbt is the whole requirement, use the dbt
semantic models. Either way the metric definitions do not move.
