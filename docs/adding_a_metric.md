# Adding a metric

How to add a metric when the source data is already in the warehouse — no new
source system, no new ingestion. Every command and every result below was run
against this repo. (The examples are illustrations, not agreed metrics, so
they are not committed.)

**If you think in SQL, work the way section 2 describes:** write the query
against the dimensional model, get the number right, then translate it into a
metric definition. The definition is how the metric gets governed, tested and
published to the warehouse, the dashboards, Power BI and the AI agent — but it
is not where you have to start.

The short version, once you know what the metric is:

```bash
$EDITOR semantic/metrics/<name>.yml        # 1. define it
$EDITOR seeds/process_metric_map.csv       # 2. put it on a dashboard (optional)
python scripts/regenerate.py               # 3. compile SQL, registry, dashboard views
dbt build                                  # 4. build and test
python scripts/test_metric_parity.py       # 5. check it reconciles
python scripts/export_powerbi.py           # 6. add the DAX measure to Power BI
```

---

## 1. The shape every metric takes

A metric here is always **a ratio of two aggregates over one fact table**:

```
metric = aggregate(column [where filter])      numerator
         -------------------------------
         aggregate(column [where filter])      denominator

         over the rows of one fact, [where metric-level filters]
         sliceable by the dimensions that fact joins to
```

A "plain" measure fits too: an average order value is `sum(amount) /
count(line)`. The grammar is deliberately small, because every definition has
to translate exactly into both SQL and DAX:

- **Aggregations:** `sum`, `count`, `count_distinct`, `avg`, `min`, `max` —
  over a bare column, never an expression.
- **Filters:** `{column, op, value}`, where `op` is one of `is_true`,
  `is_false`, `is_null`, `is_not_null`, `eq`, `ne`, `gt`, `gte`, `lt`, `lte`,
  `in`. A filter compares a column of the fact with a constant — never with
  another column.

Anything that does not fit that shape — arithmetic, a comparison between two
columns, a join to another fact — belongs in the fact model as a column, where
it is tested once and reused by every metric.

---

## 2. Start from SQL

The worked example is **Order Line Cancellation Rate**: of all sales order
lines, how many were cancelled?

### 2.1 Write the query against the star

`scripts/q.py` gives you the whole warehouse, with every layer resolvable by
bare name (`python scripts/q.py` for a prompt, `-d <table>` to describe one).
Write the query the way you normally would — against the facts and dimensions
in `main_core`, not against staging or the sources.

```sql
select count(*) filter (where order_status = 'Cancelled')           as cancelled_lines,
       count(*)                                                     as order_lines,
       round(100.0 * count(*) filter (where order_status = 'Cancelled')
             / count(*), 1)                                         as cancellation_pct
from fct_sales_order_line;
```

```
  cancelled_lines  order_lines  cancellation_pct
  ---------------  -----------  ----------------
  457              11575        3.9
```

Slice it the way a dashboard would, through a dimension:

```sql
select s.site_name,
       count(*) filter (where f.order_status = 'Cancelled')         as cancelled_lines,
       count(*)                                                     as order_lines,
       round(100.0 * count(*) filter (where f.order_status = 'Cancelled')
             / count(*), 1)                                         as cancellation_pct
from fct_sales_order_line f
join dim_site s on s.site_code = f.site_code
group by 1 order by 1;
```

```
  site_name                       cancelled_lines  order_lines  cancellation_pct
  ------------------------------  ---------------  -----------  ----------------
  Dallas TX Distribution Center   211              4832         4.4
  Reno NV Distribution Center     178              4853         3.7
  Toronto ON Distribution Center  68               1890         3.6
```

Keep these results. They are what you will check the compiled metric against.

**Write it so it will translate.** One fact in the `FROM`. Numerator and
denominator as separate aggregates, each with at most one `FILTER (WHERE ...)`
comparing a fact column with a constant. Joins to dimensions only to slice or
label, never to filter the population. If you cannot write it that way, see
§2.4 before going further.

### 2.2 Put it in metric shape

Rewrite it as numerator and denominator, grouped by the dimension keys, with no
ratio:

```sql
select order_date_key as date_key, customer_key, site_code, item_code,
       count(*) filter (where order_status = 'Cancelled') as numerator,
       count(*)                                           as denominator
from fct_sales_order_line
group by 1, 2, 3, 4;
```

```
  date_key  customer_key  site_code  item_code  numerator  denominator
  --------  ------------  ---------  ---------  ---------  -----------
  20260511  X3-C01042     US001      FG-10448   0          1
  20251105  X3-C01342     US001      RM-10189   0          1
  ...
```

This is exactly the table the compiler will generate as
`mtr_order_cancellation_rate`, and it is why the ratio is left out: every
consumer rolls a metric up by **summing the numerator and the denominator
separately**, then dividing. Averaging per-row ratios gives a different, wrong
number — even across three sites:

```
  avg_of_ratios  ratio_of_sums
  -------------  -------------
  3.88           3.95
```

### 2.3 Translate it clause by clause

| In your SQL | In the YAML | This example |
|---|---|---|
| `FROM fct_...` | `base_model` | `fct_sales_order_line` |
| What one row of the `FROM` is | `grain` | `One sales order line.` |
| Numerator aggregate | `numerator.agg` + `numerator.column` | `count` of `sales_order_line_number` |
| Its `FILTER (WHERE ...)` | `numerator.filter` | `{column: order_status, op: eq, value: Cancelled}` |
| Denominator aggregate | `denominator.agg` + `.column` + optional `.filter` | `count` of `sales_order_line_number` |
| `WHERE` on the fact, applying to both sides | `filters` (a list) | `[]` |
| The `GROUP BY` dimension keys | `dimensions` | `[date, customer, site, item]` |
| Joins to `dim_*` for slicing or labels | nothing — declared once in `semantic/models.yml` and `semantic/dimensions.yml` | |
| `100.0 * ... / ...`, `round(...)` | `format`, `decimals` | `percent`, `1` |

Operators map directly: `=` → `eq`, `<>` → `ne`, `>` `>=` `<` `<=` → `gt`
`gte` `lt` `lte`, `IN (...)` → `in` with a list, `IS NULL` / `IS NOT NULL` →
`is_null` / `is_not_null`, a bare boolean column → `is_true`, `NOT col` →
`is_false`.

`count(*)` becomes a count of a column that is never null — the grain key is
the natural choice. Then add the fields SQL does not have: a business
`description`, `lineage_notes`, `owner`, `status`. The finished file is in
[Case A, step 1](#step-1-write-the-definition).

### 2.4 What does not translate, and where it goes instead

| In your SQL | Why it does not translate | Do this instead |
|---|---|---|
| `CASE WHEN`, arithmetic, `a <= b` between two columns | Filters compare a column with a constant; aggregates take a bare column | Add the expression to the fact as a column, then filter or aggregate it — **Case B** |
| `WHERE` on a dimension attribute, e.g. `s.country_code = 'US'` | Metric filters apply to the fact's own columns | If it is a *slice*, leave it out: users filter by it at query time (`ask_metric.py --where site.country_code=US`, or a Power BI slicer). If it is *part of the definition*, carry the attribute onto the fact |
| Numerator from one fact, denominator from another | A ratio across two facts cannot be sliced coherently | Fold both onto one grain as columns — how Return Rate carries `returned_amount_usd` on the order line |
| Window functions, subqueries, `HAVING`, dedup logic | Not expressible as a single aggregate | Do it in the fact or an intermediate model; the metric reads the result |
| `count(distinct ...)` | Fine to use, but a distinct count cannot be summed across groups | Allowed. The compiler marks the metric not re-aggregatable and computes it from the fact, not from `mtr_*` |
| Relying on nulls to fall out of a denominator | `count(col)` skips nulls silently | Say it explicitly: `filter: {column: ..., op: is_not_null}` |

### 2.5 Compile, then compare with your SQL

Write the YAML, then `python scripts/regenerate.py` and `dbt build`. The
compiler writes your metric-shaped query back out as a dbt model:

```sql
-- models/marts/metrics/mtr_order_cancellation_rate.sql  (generated)
with base as (

    select
        order_date_key as date_key,
        customer_key,
        site_code,
        item_code,
        count(sales_order_line_number) filter (where order_status = 'Cancelled') as numerator,
        count(sales_order_line_number) as denominator

    from {{ ref('fct_sales_order_line') }}
    group by 1, 2, 3, 4

),
...
        cast(numerator as double) / nullif(denominator, 0) as metric_value,
```

Compare that with §2.2 — it should read like your own query. Then ask for the
metric the way a user would, and have it show its SQL:

```bash
python scripts/ask_metric.py order_cancellation_rate --by site.site_name --sql
```

```sql
select
    site.site_name,
    sum(m.numerator) as numerator,
    sum(m.denominator) as denominator,
    sum(m.numerator) / nullif(sum(m.denominator), 0) as value
from main_metrics.mtr_order_cancellation_rate as m
    join main_core.dim_site as site on site.site_code = m.site_code
group by 1
order by 1
```

```
Order Line Cancellation Rate (active)

  Dallas TX Distribution Center             4.4%    (n = 4,832)
  Reno NV Distribution Center               3.7%    (n = 4,853)
  Toronto ON Distribution Center            3.6%    (n = 1,890)
```

Same counts as your query in §2.1, row for row. And the parity check confirms
the generated model agrees with the fact:

```
  [PASS] order_cancellation_rate          0.039482 == 0.039482
```

If the numbers differ from your SQL, the definition does not say what your
query says — usually a filter on the wrong side, or nulls your query dropped
implicitly. `--sql` and the generated `mtr_*.sql` show exactly what the
compiler understood.

From here, the metric is governed like every other one: the same definition
produces the Power BI measure, the dashboard tile, the catalogue entry and the
agent contract.

---

## 3. Which case are you in?

| Situation | Case |
|---|---|
| Your query translates as it stands (§2.3) | **A** — a YAML file and a seed row |
| Your query needs an expression the grammar cannot hold (§2.4): a comparison between two columns, arithmetic, a flag | **B** — add a column to the fact, then A |
| No fact exists at the grain your `FROM` needs | **C** — build the fact, then A |

---

## Case A: the fact already has the columns

Continuing **Order Line Cancellation Rate**. `fct_sales_order_line` already
carries `order_status`, so nothing in the model changes.

### Step 1. Write the definition

`semantic/metrics/order_cancellation_rate.yml` — the filename must match
`name`:

```yaml
name: order_cancellation_rate
label: Order Line Cancellation Rate
status: active

description: >
  The share of sales order lines that were cancelled. A cancelled line is
  demand the business accepted and then did not fulfil, so a rising rate is an
  early signal of supply, pricing or credit problems.

grain: One sales order line.

base_model: fct_sales_order_line

numerator:
  agg: count
  column: sales_order_line_number
  filter: {column: order_status, op: eq, value: Cancelled}
  label: Cancelled lines

denominator:
  agg: count
  column: sales_order_line_number
  label: Order lines

filters: []

dimensions: [date, customer, site, item]

format: percent            # percent | currency_usd | days | count
decimals: 1
direction: lower_is_better

owner: TBD
owner_proposed: Director of Sales Operations

lineage_notes: >
  sage_x3.SORDER.ORDSTA_0, decoded through the APLSTD local menu (chapter 415)
  to order_status on fct_sales_order_line. The status is the order header's, so
  every line on a cancelled order counts as cancelled. Dated on the order date.

blocked_reason: null
```

`description` is what an analyst reads; `lineage_notes` is what makes the
number auditable later — name the source columns and every assumption.
`owner` stays `TBD` until someone signs off, but the field must be there.
`dimensions` can only name dimensions the base fact is bound to in
`semantic/models.yml`.

Other optional fields used by existing metrics: `provisional_reason` (required
when `status: provisional`, naming the business decision still open),
`caveats` (a list that travels with the number in `ask_metric.py`),
`companion_metric`, and `is_data_quality`. See `semantic/metrics/` for
examples.

### Step 2. Put it on a dashboard

Add one row to `seeds/process_metric_map.csv`:

```
O2C,order_cancellation_rate,M4,4
```

`process_code, metric_name, slot, display_order`. A process holds at most four
metrics, one per slot. Skip this step to register the metric without showing it
on a dashboard; add two rows to show it on two.

### Step 3. Regenerate

```bash
python scripts/regenerate.py
```

```
  ok  staging models
  ok  schema contract
  ok  metric artefacts
  ok  process views
```

That wrote, from the one YAML file:

```
?? models/marts/metrics/mtr_order_cancellation_rate.sql   the SQL model
 M models/marts/metrics/_metrics__models.yml              its dbt docs
 M seeds/metric_registry.csv                              the registry seed
 M docs/metric_catalog.md                                 the catalogue entry
 M models/marts/process/mart_o2c.sql                      the O2C dashboard view
 M models/marts/process/_process__models.yml
```

plus `exports/semantic/metric_registry.json`, which `ask_metric.py` reads.
Commit the generated files alongside your YAML: `regenerate.py --check` fails
in CI if they are out of step with the definition.

### Step 4. Build and test

```bash
dbt build
```

```
Done. PASS=315 WARN=4 ERROR=0        (both examples in this guide added)
```

Four warnings is normal — they are the documented data-quality findings. A
typo in the seed map fails here, on the test that ties the map to the registry.

### Step 5. Check the number

Compare with your SQL as in [§2.5](#25-compile-then-compare-with-your-sql),
and run the parity check, which reconciles every metric model against its
fact:

```bash
python scripts/test_metric_parity.py
```

Then on the dashboard view:

```bash
python scripts/q.py "select slot, metric_label, metric_status,
  round(sum(numerator)/nullif(sum(denominator),0),4) as value
  from mart_o2c group by 1,2,3 order by 1"
```

```
  slot  metric_label                  metric_status  value
  ----  ----------------------------  -------------  ----------
  M1    DSO (days-to-pay proxy)       provisional    47.9627
  M2    Return Rate                   provisional    0.0127
  M3    Cost Per Order                provisional    1,560.7837
  M4    Order Line Cancellation Rate  active         0.0395
```

### Step 6. Power BI

```bash
python scripts/export_powerbi.py
```

```
  14 tables, 22 relationships, 11 generated measures, 0 hand-written
```

The measure lands on its base table in the generated model, compiled from the
same YAML as the SQL:

```
measure 'Order Line Cancellation Rate' = DIVIDE(
    CALCULATE(COUNTA(fct_sales_order_line[sales_order_line_number]),
              fct_sales_order_line[order_status] = "Cancelled"),
    COUNTA(fct_sales_order_line[sales_order_line_number]))
    formatString: "0.0%"
    displayFolder: Metrics
```

Refresh the model in Power BI (see [powerbi_model.md](powerbi_model.md)). If
you have Power BI open, `python scripts/test_metric_parity.py --write-dax-gate`
writes a query per metric to `exports/powerbi/parity/` with the answer the
warehouse expects.

---

## Case B: the fact needs a new column first

**Example: Shipped by Requested Date** — the share of shipped order lines that
left on or before the date the customer asked for. In SQL it is one line:

```sql
select count(*) filter (where shipment_date <= requested_delivery_date) as on_time,
       count(*) filter (where shipment_date is not null)                as shipped,
       round(100.0 * count(*) filter (where shipment_date <= requested_delivery_date)
             / count(*) filter (where shipment_date is not null), 1)    as pct
from fct_sales_order_line;
```

```
  on_time  shipped  pct
  -------  -------  ----
  8033     10421    77.1
```

But `shipment_date <= requested_delivery_date` compares two columns, which a
filter cannot do. So the comparison moves onto the fact, and the metric filters
on the result.

### Step 1. Add the column to the fact

In `models/marts/core/fct_sales_order_line.sql`, next to the other flags in the
`final` CTE:

```sql
        -- Flags
        joined.shipped_qty >= joined.ordered_qty                as is_fully_shipped,
        case
            when joined.shipment_date is null then null
            else joined.shipment_date <= joined.requested_delivery_date
        end                                                     as is_shipped_by_request_date,
```

Null where there is no ship date, rather than false, so unshipped lines drop
out of the denominator instead of counting as late — the same population as
your query's denominator.

Describe the column in `models/marts/core/_core__models.yml` under the fact,
and add a test if the column has a rule worth asserting. Run
`dbt build --select fct_sales_order_line` and re-run your query against the new
column to confirm it gives the same 8,033 / 10,421.

### Step 2. Define the metric against the new column

`semantic/metrics/shipped_by_request_date_rate.yml` — same shape as Case A;
the parts that differ:

```yaml
name: shipped_by_request_date_rate
label: Shipped by Requested Date
status: active
grain: One shipped sales order line.
base_model: fct_sales_order_line

numerator:
  agg: count
  column: sales_order_line_number
  filter: {column: is_shipped_by_request_date, op: is_true}
  label: Lines shipped by the requested date

denominator:
  agg: count
  column: sales_order_line_number
  filter: {column: is_shipped_by_request_date, op: is_not_null}
  label: Shipped lines

filters: []
dimensions: [date, customer, site, item]
format: percent
direction: higher_is_better
```

### Step 3. Continue from Case A, step 2

Map it to a dashboard or not (this example stays on none), then regenerate,
build and check. It matches the SQL:

```
  [PASS] shipped_by_request_date_rate     0.770847 == 0.770847
```

```
Shipped by Requested Date (active)

         77.1%    (n = 10,421)
```

---

## Case C: no fact at the right grain

When no fact's row is the thing your denominator counts — say a metric on
purchase order lines, which no fact holds today — your query will want to
start `FROM` a staging model. That query is the first draft of a new fact. The
data is already in staging (`stg_sage_x3__porderq` and friends); this is
modelling work only.

1. **Write the fact.** `models/marts/core/fct_<event>.sql`, from your query's
   `FROM` and joins. State the grain in a comment at the top. Read from
   staging and intermediate models only. Coalesce every dimension key to
   `'UNKNOWN'`, and add date keys as `yyyymmdd` integers, like the existing
   facts. Put derived flags and amounts on the fact now, so the metric can be
   a plain Case A. The smallest template is `fct_inventory_count_line.sql`;
   `fct_supplier_invoice_line.sql` shows one built on an intermediate matching
   model.
2. **Test it.** An entry in `models/marts/core/_core__models.yml` with the grain
   in the description, `dbt_utils.unique_combination_of_columns` on the grain,
   and a `relationships` test from every dimension key to its dimension.
3. **Bind it.** An entry in `semantic/models.yml` naming the column that reaches
   each conformed dimension, plus any degenerate attributes:

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

4. **Expose it to Power BI.** Add the table to `CORE_TABLES` and its keys to
   `RELATIONSHIPS` in `scripts/export_powerbi.py`. Optionally add it to
   `CORE_TABLES` in `scripts/verify_ingestion.py` too.
5. **Add the metric**: rewrite your query against the new fact (§2), then
   Case A.

Facts already named and grained, so the decision is made once rather than
rediscovered: `fct_purchase_order_line` (`POHNUM_0` + `POPLIN_0`),
`fct_inventory_movement` (`STOJOU.ROWID`), `fct_inventory_balance` (item ×
site × lot snapshot), `fct_gl_entry_line` (`NUM_0` + `LIN_0`), `fct_forecast`
(item × location × period snapshot), `fct_deal_stage_change` (`deal_id` +
transition), `fct_payroll_earning` (`check_id` + `earning_code`).

---

## When the data is not there

Register the metric anyway, as `status: blocked` with a `blocked_reason` and
`unblock_requires`, and no base model or SQL. It costs nothing, and the
dashboard and `ask_metric.py` show why the number is missing instead of
showing nothing. See [architecture.md §3](architecture.md#3-runbook-adding-a-metric).

---

## When something goes wrong

The compiler validates every definition before it writes anything. Real
messages for common mistakes:

```
Registry validation failed:
  - ...: base_model 'fct_sales_order_line' has no binding for dimension 'carrier' - add it to semantic/models.yml
  - ...: numerator.expression is no longer supported. Rename it to 'column' - it must be a bare column on fct_sales_order_line, and any derivation belongs on the fact model.
  - ...: filters[0]: op 'like' unknown; expected one of ['eq', 'gt', 'gte', 'in', 'is_false', 'is_not_null', 'is_null', 'is_true', 'lt', 'lte', 'ne']
  - ...: provisional metrics must state provisional_reason
```

| Symptom | Fix |
|---|---|
| The metric's number differs from your SQL | Compare `ask_metric.py <name> --sql` and the generated `mtr_<name>.sql` with your query. Usually a filter on the wrong side (numerator vs `filters`), or nulls your query dropped implicitly. |
| `has no binding for dimension` | The base fact cannot reach that dimension. Drop it from `dimensions`, or add the key to the fact and bind it in `semantic/models.yml`. |
| `expression is no longer supported` | Put the arithmetic on the fact as a column (Case B) and point the metric at it. |
| `op '...' unknown` | Only the ops listed in §1 exist. A column-to-column comparison is Case B. |
| `note: column existence NOT checked` | Not an error — the column check needs `target/catalog.json`. Run `dbt docs generate`, then `python scripts/compile_metrics.py --check`, to catch a misspelt column before `dbt build` does. |
| `process_metric_map references unknown metric(s): [...]` | The seed row's `metric_name` does not match any YAML `name`. |
| dbt fails `assert_metric_slots_are_within_four` or `process_metric_map_one_metric_per_slot` | The process already has four metrics, or the slot is taken. |
| Parity prints `[ -- ] not re-aggregatable` | Expected for a `count_distinct`. The metric is computed from the base fact in Power BI and `ask_metric.py`; do not sum its `mtr_*` model. |
| Parity `FAIL` | The pre-aggregated model disagrees with the fact — usually a filter or dimension choice. Fix the definition before shipping. |

To change an existing metric, edit its YAML and run the same steps from
step 3. To take a metric off a dashboard, delete its seed row; to move it,
change the row.
