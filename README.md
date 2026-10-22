# Control Tower

An open-source baseline data platform: three source systems through bronze,
silver and gold into a **MetricFlow semantic layer** that defines every measure
once, feeding process and department dashboards, data marts, agentic AI chat,
apps built with AI coding tools, and apps with embedded AI. Every component sits
behind a written contract with a test, so any one of them can be swapped for
another tool - which is what makes it the reference implementation a software
evaluation is measured against. The source systems are simulated, so the
whole platform runs end to end on a laptop, in CI and in Azure.

[PLAN.md](PLAN.md) is the design and the decisions; [docs/](docs/) is the
platform as built.

## Run it

```bash
make setup     # Python 3.11 + uv
make mock      # the synthetic sources as of 2026-09-05
make run       # ingest, build, MDM, cubes, serving load
make golden    # the golden answers: every route gives the same numbers
make test      # unit and conformance tests
make serve     # REST + MCP on http://localhost:8000
make ui        # Dagster on http://localhost:3000
make studio    # the architecture and a live pipeline walk-through, http://localhost:8800
```

## The stack

| Component | Open-source baseline | Where |
|---|---|---|
| Sources (simulated) | Sage X3 (SQL Server + CDC), HubSpot (REST), Netstock (snapshot) | `sources/` |
| Ingestion, CDC | dlt → append-only Delta changelog | `ingestion/` |
| Raw storage | ADLS Gen2 (`.data/` locally) | `infra/modules/storage.bicep` |
| Master data | Splink, with a rules matcher for comparison | `mdm/` |
| Transformation | dbt Core | `transform/` |
| Warehouse, compute | DuckDB | `transform/profiles.yml` |
| Semantic layer | MetricFlow YAML + governance + the process × department matrix | `transform/models/semantic/`, `semantic/` |
| Dashboards | Power BI importing one cube MetricFlow computed; generated model, templated measures | `serving/powerbi.py`, `powerbi/` |
| Cubes, marts, apps | Saved queries → cubes → Postgres; REST API | `serving/`, `apps/data_service/` |
| Applied AI | MCP server for Claude Code; embedded example on the Claude API | `apps/` |
| Orchestration | Dagster | `orchestration/` |
| Cloud, CI/CD | Azure (Bicep), GitHub Actions | `infra/`, `.github/` |
| Evaluation | component registry, golden answers, scorecard | `evaluation/` |

## Where things stand

All 37 golden answers pass on DuckDB. Bronze converges exactly on every source
table through daily CDC, a retention gap and hard deletes. The MDM providers
score 0.90/0.91 (Splink) and 0.86/0.93 (rules) on customer precision/recall
against the generator's true identities. The 21 golden answers a dashboard
cube can serve come back identically through the cube and the Power BI
measure templates, rollups included.

| Metric | Value (as of 2026-09-05) | Status |
|---|---|---|
| On-Time Delivery | 70.1% | provisional |
| Order Fill Rate | 94.4% | provisional |
| Return Rate | 1.1% | provisional |
| DSO (days-to-pay proxy) | 47.0 days | provisional |
| Unsettled Invoice Rate | 21.0% | active |
| Match Rate | 70.5% | provisional |
| Inventory Accuracy | 93.2% | provisional |
| Forecast Accuracy | 71.0% | provisional |
| Win Rate | 66.2% | provisional |
| Customer Match Rate | 82.3% | active, data quality |

Plus Pipeline Value, Sales Cycle Days, Revenue, Trailing 90-day Revenue and
Platform Cloud Cost, and four backlog metrics that return reasons instead of
numbers. Full list: [docs/metric_catalog.md](docs/metric_catalog.md).

Not yet verified: the generated Power BI model opened in Desktop (needs
Windows), the Azure deployment, and the T-SQL path's execution (CI runs it
against SQL Server; this repo's machine has no Docker).

## Documentation

| Document | For |
|---|---|
| [docs/architecture.md](docs/architecture.md) | The design: layers, contracts, the semantic layer, the five routes |
| [docs/components.md](docs/components.md) | Each component, its contract, and how to swap it |
| [docs/running.md](docs/running.md) | Commands, the Studio, incremental refresh, the data service, Dagster, environments |
| [docs/adding_a_metric.md](docs/adding_a_metric.md) | From SQL to a governed metric on every route |
| [docs/sources.md](docs/sources.md) | The synthetic sources, the clock, the landmines |
| [docs/powerbi.md](docs/powerbi.md) | The cube, the generated model and the pages to build |
| [docs/evaluation.md](docs/evaluation.md) | How the baseline evaluates other tools |
| [docs/open_questions.md](docs/open_questions.md) | What is assumed, and what it costs to reverse |
