# Adding a metric

A metric is defined once, in MetricFlow YAML, and every route picks it up:
the cubes and the Power BI model over them, the data service, the MCP tools,
the catalog. Which dashboards show it is a seed row, not part of the definition.

## 1. Start from SQL

Write the number as a query against gold first - it is the reference you will
check against.

```sql
-- Share of supplier invoice lines that matched, by site
select s.site_name, sum(f.is_three_way_matched) * 1.0 / sum(f.invoice_line_count)
from gold.fct_supplier_invoice_line f
join gold.dim_site s on s.site_code = f.site_code
group by 1;
```

## 2. Which case are you in?

**A. The fact already has the columns.** The common case. Go to step 3.

**B. The fact has the inputs but not the column.** A comparison of two
columns, or arithmetic. Add the column to the fact (and its contract in
`_gold__models.yml`) first: measures are aggregations over a bare column, and
the lint rejects anything else. Arithmetic in the fact is tested, and every
route sees the same column.

**C. No fact at the right grain.** Build the fact in `models/gold/`, add its
contract and tests, then a semantic model for it in
`models/semantic/semantic_models.yml` naming its entities (the joins
MetricFlow may follow - include `employee` if the activity has a person, so
department dashboards can cut it).

**D. The data does not exist yet.** Add it to `projects/<slug>/backlog.yml` as
`blocked` (with `blocked_reason` and `unblock_requires`) or `placeholder`
(with `placeholder_reason`). It costs nothing, appears in the catalog with the
reason, and the API and MCP tools return the reason instead of a number.

## 3. Define it

Add measures to the fact's semantic model if they are new, then the metric to
`models/semantic/metrics.yml`:

```yaml
  - name: supplier_on_time_receipt_rate
    label: Supplier On-Time Receipt
    description: The share of PO lines received on or before the expected date.
    type: ratio
    type_params: {numerator: on_time_receipts, denominator: received_po_lines}
    config:
      meta:
        role: kpi
        status: provisional                  # or active
        owner: TBD
        owner_proposed: Purchasing Manager
        provisional_reason: Whether partial receipts count is undecided.
        caveats: [Receipts post up to three days after arrival.]
        format: percent                      # percent | currency_usd | days | count
        direction: higher_is_better
```

Ratio numerators and denominators are metrics: define the two simple metrics
(`role: component`) first. If the ratio needs a filter, put it on both
components, not on the ratio: then the ratio stays a plain ratio of two sums
and rolls up on dashboards (`Order Fill Rate` does this). How each metric rolls
up - `sum`, `ratio` or `fixed` - is read from its definition
(`semantic/rollup.py`) and shown in the catalog.

## 4. Put it on dashboards

- **Governance:** one row in `seeds/process_metric.csv` per process dashboard
  (slot `M1`-`M4`), and one row in `seeds/department_metric.csv` per
  department whose activities own or contribute to it in that process.
- **Data:** add it to the saved queries in `models/semantic/saved_queries.yml`
  whose pages show it - at least `mart_company_monthly` for a business KPI
  (the lint requires every KPI to be in one). A `fixed` metric shows only at
  a cube's own grain, so give it a cube at every grain a page needs.
- **Report:** place the new measure on the page ([powerbi.md](powerbi.md)).

## 5. Build and check

```bash
python -m ctl dbt parse          # MetricFlow reads the YAML
python -m semantic.lint          # governance
python -m ctl dbt build          # if you changed models or seeds
python -m semantic.catalog       # projects/<slug>/docs/metric_catalog.md
python -m ctl materialize        # the cubes gain the metric
python -m ctl powerbi            # the Power BI model gains the measure
```

Then compare with your SQL from step 1:

```python
from serving.semantic_service import SemanticService
SemanticService().query(["supplier_on_time_receipt_rate"], group_by=["site__site_name"])
```

Add a golden answer to `projects/<slug>/golden_answers.yml` with your SQL as
`reference_sql`, then `python -m evaluation.golden freeze` and commit the diff.
CI will hold every route to that number from now on.

## What the lint refuses

- a KPI with no owner, no description, or a status outside active/provisional
- provisional with no `provisional_reason`; a backlog entry with no reason
- a measure over an expression instead of a bare column
- a KPI that is in no saved query, so no dashboard could show it
- a seed row naming a metric that does not exist
- a gold model without an enforced contract or an owner
