# Power BI

Power BI computes nothing of its own. MetricFlow computes every number into
**one table, `marts.dashboard_cube`**, and Power BI imports that table and
draws it. No measure logic lives in Power BI, and no DAX is translated from
the semantic layer.

## The cube

Each saved query in `projects/<slug>/models/semantic/saved_queries.yml` is one
cube: a fixed set of metrics at a fixed grain (for example, the O2C metrics by
site and month). `python -m ctl materialize` computes each one through
MetricFlow, then stacks them all into `dashboard_cube`:

| Column | What it holds |
|---|---|
| `_cube` (shown as **Cube**) | Which saved query the row came from |
| Dimensions (**Month**, **Site Name**, **Department Name**, ...) | Shared across cubes; null in a cube that doesn't carry them |
| One column per metric | The value MetricFlow computed at the cube's grain (hidden) |
| Numerator and denominator of every ratio | So ratios roll up correctly (hidden) |

It's small: about 5,000 rows by 42 columns on the synthetic data, far below
anything that troubles Power BI's in-memory engine. Every cube and its grain
is listed at the end of [metric_catalog.md](../projects/sample_v2/docs/metric_catalog.md#dashboard-cubes).

## The model

`python -m ctl powerbi` generates the model as TMDL in
`projects/<slug>/powerbi/ControlTower.SemanticModel/definition/`, from the manifests alone.
It has one table and one measure per KPI. Every measure is one of three
templates, picked from the metric's definition (`semantic/rollup.py`):

| Rollup | Metrics | Measure |
|---|---|---|
| `sum` | sums and counts | `IF(HASONEVALUE([Cube]), SUM([metric]))` |
| `ratio` | a ratio of two sums | `IF(HASONEVALUE([Cube]), DIVIDE(SUM([numerator]), SUM([denominator])))` |
| `fixed` | distinct counts, averages, derived and cumulative metrics | `IF(COUNTROWS(dashboard_cube) = 1, MAX([metric]))` |

The guards make a wrong number impossible to show:

- **Rows from two cubes never add up.** A sum or ratio is blank unless the
  visual is filtered to exactly one Cube.
- **Sums and ratios roll up correctly** from a cube to any coarser grain, and
  to totals: a by-month line from a site-by-month cube is right.
- **A fixed metric shows only where a visual lands on exactly one stored
  row.** Anywhere else (a total, an unselected slicer, a grain the cube
  doesn't have) it is blank, never an average of averages.
- **A slicer on a dimension a cube doesn't carry** empties that cube's
  visuals rather than ignoring the selection.

So the worst a report mistake can do is show a blank. `discourageImplicitMeasures`
is on and the value columns are hidden, so authors can only use the measures.

**Status: generated and checked structurally, not yet opened in Power BI
Desktop.** That needs Windows (open question Q-F). If it does not open
cleanly, fix the generator, not the model.

## Building the pages

The reports are part of what we deliver, so one rule covers them:
**filter every page or visual to one Cube whose grain covers everything that
filters the visual** (its axes, its slicers, and cross-filtering from other
visuals).

- **A page per process** (O2C, I2D, S2P, P2C, F2P, R2P). A page-level filter
  on its cube (`mart_o2c`, ...) drives the site breakdowns and site slicer.
  The headline cards and company trend lines use a visual-level filter on
  `mart_company_monthly` instead, with **Edit interactions** set so the site
  slicer doesn't filter them.
- **The department page.** A page filter on `mart_department_scorecard`; a
  matrix with KPIs as rows (*Switch values to rows*) and **Department Name**
  as columns, plus a month slicer.
- **Account reviews.** `mart_customer_scorecard`, with a customer slicer.
- **Platform Health.** `mart_platform_cost`, cost by component and month.

Showing a fixed metric (Forecast Accuracy, Trailing 90-day Revenue) both by
site and company-wide takes two cubes, one at each grain. Adding a metric to
a page means adding it to the saved query, `make run`, `python -m ctl powerbi`,
and placing the measure on the page.

Which process and department each metric belongs to is governance, not data:
it lives in the dashboard seeds and shows in [metric_catalog.md](../projects/sample_v2/docs/metric_catalog.md),
together with the backlog metrics and why they have no number.

## Opening it

1. `make run`, then `python -m ctl powerbi` (the model only changes when the
   semantic layer does).
2. In Power BI Desktop, create a Power BI Project (`File > Save as > .pbip`)
   once and commit it under `projects/<slug>/powerbi/`, then point its semantic model at the
   generated `ControlTower.SemanticModel` folder - or open the folder in
   Tabular Editor.
3. Set the `MartFolder` parameter to `.data/exports/marts/` (absolute path,
   trailing separator) with `MartSource = "local"`, or to the
   `https://<account>.dfs.core.windows.net/exports/<env>/marts/` URL with
   `MartSource = "adls"` (no gateway needed).
4. Refresh.

## Parity: proving it matches

`python -m ctl powerbi` also writes `projects/<slug>/powerbi/parity/parity_queries.json`: each
golden answer that some cube can serve (21 of them), as the DAX query a
visual would run, with the frozen answer beside it.

- **Locally and in CI:** `python -m serving.powerbi_parity local` runs the
  same queries with each template's SQL twin over the materialised cube.
  This proves, without Power BI, that the cube plus the templates reproduce
  MetricFlow's answers, rollups included. `tests/conformance/test_dashboard_cube.py`
  runs it.
- **Against the deployed model:** `python -m serving.powerbi_parity run`
  sends the DAX through the Power BI REST `executeQueries` API. CD runs it in
  the test environment after each deployment.

## Deployment

The model deploys from TMDL to one workspace per environment. How depends on
licensing (open question Q-D): deployment pipelines and the XMLA endpoint
need Premium, PPU or Fabric capacity; with Pro, publish from Desktop or use
the Fabric item-definition API where available. One shared model serves every
report.
