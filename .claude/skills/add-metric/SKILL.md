---
name: add-metric
description: Add or change a governed metric in the semantic layer - from a reference SQL query to a MetricFlow definition on every route (cubes and Power BI, marts, API, MCP), with dashboard seeds, lint, catalog and a golden answer. Use when asked to add, change, define or block a KPI or measure.
---

Follow docs/adding_a_metric.md. A metric belongs to one project pack (`projects/<slug>/`, default `sample_v2`; ask which if it is not obvious) and every command below runs on it (`CT_PROJECT=<slug>`). In order:

1. Write the metric as SQL against gold and run it (`duckdb .data/<slug>/warehouse.duckdb`). This is the reference.
2. Decide the case: A (fact has the columns), B (add a column to the gold fact and its contract first - measures are aggregations over bare columns only), C (new fact + contract + semantic model with entities, including `employee` when a person performs the activity), D (no data: add to projects/<slug>/backlog.yml as blocked or placeholder with the reason).
3. Add measures to `projects/<slug>/models/semantic/semantic_models.yml` if needed and the metric to `metrics.yml` with full `config.meta` (role, status, owner - TBD is fine, provisional_reason if provisional, caveats, format, direction, and `requirement: <dashboard code>-<slot>` when a dashboard slot in the project's requirements asked for it). Labels must be unique within the project. Ratio inputs are component metrics; a filter goes on both components, not on the ratio, so the ratio rolls up.
4. Add a KPI to `mart_company_monthly` in `saved_queries.yml` (the lint requires every KPI in a saved query), and to the cubes of the pages that show it. Add rows to `projects/<slug>/seeds/process_metric.csv` and `department_metric.csv` only if the user named dashboards; otherwise ask.
5. Run: `python -m ctl dbt parse`, `python -m semantic.lint`, `python -m ctl dbt build` (if models/seeds changed), `python -m semantic.catalog`, `python -m ctl materialize`, `python -m ctl powerbi`.
6. Query it through `SemanticService().query(...)` and confirm it equals step 1.
7. Add a golden answer (`projects/<slug>/golden_answers.yml`, reference_sql from step 1), run `python -m evaluation.golden freeze`, and report every changed number.

Never put measure logic anywhere but the semantic YAML, and never hand-write DAX. Never name the client.
