# Components

One section per platform component: what it does here, the contract it
honours, how to swap it, and the candidates the evaluation compares. The swap
costs and the compatibility rules behind them are in [PLAN.md §9](../PLAN.md);
the machine-readable version of this page is `evaluation/components.yml`.

Swap cost: **adapter** (configuration plus a thin adapter - days), **port** (the
same logic on a new engine - weeks), **rebuild** (logic re-expressed in another
tool and re-verified with the golden answers).

## Cloud infrastructure - Azure, Bicep

`infra/main.bicep` and one module per component, one parameter file per
environment. Every resource is tagged `env`, `component`, `stack`, `owner`; the
component tag is what turns the cost export into cost by component. No keys:
one user-assigned managed identity reaches storage, Key Vault and Postgres.

## Master data management - Splink, with a rules matcher

`mdm/`. Matches HubSpot companies to X3 customers (no shared key) and X3
users, X3 reps and HubSpot owners to one person. Splink weighs name, core
name, domain stem and country probabilistically; the rules matcher is v1's
four deterministic probes. Employees match on email then name in both.
Output is contract C3, landed in raw storage where an external product's
export would land.

**Swap:** adapter. A product (Boomi Data Hub, Profisee) exports golden IDs and
source cross-references in the C3 shape; silver does not change. The product
runs outside the pipeline and is fed by the source systems, and it owns
syncing golden records back into X3 and HubSpot - out of scope here. Scored
against the generator's true identities, Splink reaches precision 0.90 /
recall 0.91 on customers, the rules matcher 0.86 / 0.93.

## Orchestration - Dagster

`orchestration/definitions.py`: one asset per source table, MDM output and
dbt model, plus marts, exports and the serving load; jobs, schedules and a
failure-alert sensor. Each asset calls a step command from `ctl` and holds no
logic; data quality checks are dbt tests, which Dagster shows as checks.

**Swap:** adapter. ADF, a Boomi Logic Flow, Fivetran schedules plus Snowflake
Tasks, or cron call the same `python -m ctl ...` steps. CI runs the pipeline
through those commands without Dagster, which proves it.

## Ingestion and change data capture - dlt

`ingestion/`. Built from the C1 specs:

| Source | Strategy | Deletes |
|---|---|---|
| Sage X3 | Snapshot once, then SQL Server CDC change tables by LSN. A gap longer than CDC retention triggers a fresh snapshot | CDC delete rows |
| HubSpot | Modified-since cursor with a 1-day lookback, archived records as a second pass; full crawl for associations, stage history, owners | key reconciliation (`--reconcile`, weekly) |
| Netstock | Full snapshot, skipped when `last_sync_at` has not moved | implicit |
| Azure cost | Append new days | - |

Source column names are kept exactly (`ITMREF_0`), columns are frozen in
`ingestion/schemas/`, and bronze is an append-only Delta changelog.

**Swap:** adapter - one bronze adapter macro per tool. Any ingestion tool
(ADF, Boomi Data Integration, Fivetran, Airbyte) must deliver deletes, change
history (append-only or a history mode) and the original column names, and
pass `tests/conformance/test_ingestion_convergence.py`. Netstock is likely a
custom connector in every tool; dlt is strong at custom REST sources.

**Production swap of the sources themselves:** `sources/simulators/` is the
seam. Each module's docstring names the real call that replaces it.

## Raw storage - ADLS Gen2 (Delta)

Containers `bronze`, `warehouse` (the published DuckDB file), `exports`
(the cubes as Parquet - what Power BI imports), `costs` (the FOCUS export).
Locally `.data/`.

**Swap:** adapter for OneLake (a shortcut to the ADLS bronze; Delta folders read
as tables); port for loading into Azure SQL or Snowflake tables.

## Transformation - dbt Core

`transform/`. Bronze, silver, gold, seeds and tests. Silver and gold follow
the portability rules - cross-database macros, no `QUALIFY`, `EXCLUDE`,
`GROUP BY ALL`, `::`, positional `GROUP BY` or `USING` - and
`python -m checks.portability` translates every model to T-SQL and Snowflake
SQL on every PR.

**Swap:** port while it stays dbt (dbt-sqlserver, dbt-fabric, dbt Projects on
Snowflake); rebuild if it leaves dbt for stored procedures or notebooks, and
tests, docs, contracts and lineage go with it. Keeping dbt is the single
biggest thing that keeps swaps cheap.

## Warehouse storage and compute - DuckDB

A single file, built by Dagster (the only writer) and published to raw storage
after each run; read-only consumers use the published copy. DuckDB has no
user-level security - access control lives in storage and the data service -
which belongs in the evaluation.

**Swap:** port. A dbt adapter plus the portable SQL; bronze's adapter macro
changes. On Azure SQL or Fabric Warehouse, MetricFlow follows through the
T-SQL path (below); on Snowflake, MetricFlow supports it directly.

## Semantic modeling - MetricFlow

`transform/models/semantic/`, `semantic/backlog.yml`, the dashboard seeds,
`serving/semantic_service.py`. See [architecture.md](architecture.md#the-semantic-layer).

**The T-SQL path (decision D10).** MetricFlow has no T-SQL renderer. The
service's `tsql` backend has MetricFlow render Postgres-style SQL, translates it
with sqlglot and runs it with pymssql. CI loads gold into a SQL Server 2022
container and runs the golden answers through it.

**Swap:** rebuild of the definitions (the Ossie converters may cut that down)
plus a new `semantic_service` backend; consumers do not change. dbt 1.12
writes `transform/target/osi_document.json` on every parse - the definitions
in the Open Semantic Interchange format, the starting point for any
translation. Candidates: Power BI or Fabric semantic models as the source of
truth, Snowflake semantic views, dbt Cloud Semantic Layer, Cube, AtScale, the
Boring Semantic Layer.

## Visualization and distribution - Power BI

Power BI imports one table, `dashboard_cube`, that MetricFlow has computed;
`serving/powerbi.py` generates the model over it, with one templated measure
per KPI and no logic of its own. Reports are built in Power BI Desktop and
published to a workspace per environment, distributed as Power BI apps. See
[powerbi.md](powerbi.md).

**Swap:** adapter - `LoadMart` in `expressions.tmdl` is the only place the
model knows where data lives (Parquet in ADLS today; Postgres, Fabric or
Snowflake tomorrow). Because the model holds no logic, any BI tool that can
import a table and do `SUM` and divide can replace it - Tableau, Superset,
Excel - reading the same cube.

## Downstream apps - the data service and Postgres

`apps/data_service/` (REST and MCP in one container) and
`serving/reverse_load.py` (dlt copies the marts to Postgres). Read-only,
audit-logged, behind Container Apps authentication in Azure.

**Swap:** adapter. Any plain Postgres works (Azure Database for PostgreSQL,
Snowflake Postgres); an integration platform reads the C7 tables or calls the
C6 API.

## Applied AI - Claude Code and MCP

The MCP server exposes five tools that only reach governed metrics;
`.mcp.json` registers it for Claude Code; `apps/examples/ask_metrics/` embeds
the same tools in an app through the Claude API; `.claude/skills/` holds the
team's runbooks (add a metric, add a source table, swap a component, run the
platform).

**Swap:** adapter for any agent platform that speaks MCP. Snowflake Cortex
Analyst grounds on Snowflake semantic views, so it follows the semantic-layer
swap.

## Added components

| Component | Here |
|---|---|
| Data quality and observability | dbt tests (warn-level on known-dirty joins), enforced contracts, the GL reconciliation, Dagster asset checks, freshness via `last_sync_at` |
| Catalog and lineage | dbt docs (`python -m ctl dbt docs generate`), the metric catalog, Dagster's asset graph from source table to dashboard export |
| Secrets and identity | Key Vault references, one managed identity, `.env` locally, gitleaks and the blocked-word check in CI |
| CI/CD and IaC | `.github/workflows/ci.yml`, `cd.yml`, `infra/` |
| Cost management | tags, budgets at 50/80/100%, the daily FOCUS export ingested into `gold.fct_cloud_cost`, `seeds/license_cost.csv` |
| Source simulation | `sources/`: the generator, the clock, the simulators |
