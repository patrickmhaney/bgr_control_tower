# Control Tower v2: POC plan

Branch: `control_tower_v2` · Drafted 2026-10-20 · Revised 2026-10-21 (D12: Power BI imports one cube; no DAX compiler) · Status: implemented on this branch (see README, "Where things stand")

> **v3 (2026-10-25, branch `control_tower_v3`): one architecture, many project
> packs.** The content this plan was built with now lives in the pack
> `projects/sample_v2/`; everything else is the architecture, identical for
> every project. Paths below that name `transform/models/`, `transform/seeds/`,
> `semantic/backlog.yml`, `evaluation/golden_answers.yml`, `ingestion/specs/`,
> `ingestion/schemas/` or `powerbi/` now resolve inside a pack
> (`projects/<slug>/...`); the staging models and macros moved to the dbt
> package `transform/platform/`. See §6 and
> [docs/architecture.md](docs/architecture.md#architecture-and-projects).

## 1. What we are building

An open-source baseline data platform on Azure. It is the reference
implementation the client's software evaluation is measured against, and the
backbone the real implementation is built on. Three source systems (Sage X3,
HubSpot, Netstock) flow through bronze, silver and gold layers into a
**MetricFlow semantic layer**. That layer is the one place a measure is
defined, and every downstream use reads from it:

- process dashboards and department dashboards (the process × department matrix)
- denormalized data marts
- agentic AI chat over the data
- apps built with AI coding tools
- apps with embedded AI

Every component sits behind a **data contract**, so a component can be swapped
for an alternative without touching its neighbours. Swapping MetricFlow for
Cube, dlt for Fivetran, DuckDB for Fabric, or Splink for a commercial MDM
means replacing one box and re-running the same conformance tests. Every
component in the POC is open source. The commercial products are what get
compared against it later. The source
systems are simulated, as they are today, so the whole platform runs end to
end on synthetic data, on a laptop, in CI and in Azure.

## 2. Design principles

1. **Contracts at every boundary, and tests that enforce them.** A component
   is replaceable only if what it must produce is written down and checked.
   §4 lists the seven contracts.
2. **Measures are defined once, in the semantic layer.** No consumer writes
   measure logic. Dashboard numbers, mart SQL and agent answers are all
   computed by MetricFlow; Power BI only sums and divides what MetricFlow
   stored (D12). Tests check that they agree.
3. **Synthetic data with a clock.** The simulators can replay any day, which
   is how incremental refresh, CDC and deletes are proven rather than
   asserted. Because the generator knows the true answers, every component can
   be scored against them.
4. **Config over code, so day-two work is YAML and SQL.** Sources, metrics,
   process and department mappings, and environments are declarative. That is
   the closest an open-source baseline gets to low-code, and it sets the bar a
   low-code alternative has to clear.
5. **Lighter than v1.** Prefer a tool's native feature to custom code (dlt
   schema contracts over our own contract module, MetricFlow over our own
   metric compiler). Delete whatever no requirement needs.
6. **Build for this client, but never name them.** Client-specific content
   lives in config, seeds and YAML, and platform code stays generic by habit.
   We add no abstraction just to make it reusable. The client's name appears
   nowhere in the repo: not in code, config, docs, data, branch names or
   commit messages. A check in CI and a pre-commit hook enforce it. The list
   of blocked words lives in a CI secret and an untracked local file, never in
   the repo, because a check that spells out the name would leak it.
7. **Keep what v1 got right.** That includes the simulator seam, the
   deliberate data-quality landmines, entity resolution you can inspect,
   metrics that no process owns, blocked and provisional statuses with
   reasons, assumptions encoded as vars, and the reconciliation test against
   the GL.

## 3. Target architecture

```
 Sage X3 (SQL Server)     HubSpot (REST)      Netstock (REST)
   CDC change tables       cursor + archived    snapshot per sync
        │                        │                    │
        └──────────── INGESTION · dlt ────────────────┘
                          │  C1 source spec + frozen schema
                          ▼
        RAW STORAGE · ADLS Gen2: bronze changelog, Parquet  C2 layout
                          │
                          ▼
        TRANSFORMATION · dbt Core  on  COMPUTE + WAREHOUSE · DuckDB
          bronze current state → silver staging ─────► MDM · Splink | rules matcher
                                 silver conformed ◄──── C3 xref + golden tables
                                 gold star
                          │  C4 enforced dbt model contracts
                          ▼
        SEMANTIC LAYER · MetricFlow YAML + governance meta + process/department matrix
                          │  C5 semantic manifest + metric catalog
       ┌──────────────┬───┴────────────┬──────────────────┬──────────────────┐
  Power BI model   Cubes + marts    Data service        Serving DB          
  imports one      saved queries    REST + MCP          Postgres            
  cube table       materialized     (one container)     (dlt reverse load)  
       │              │              │        │               │
  process ×        analysts,      Claude Code /   apps built with AI tools,
  department       exports        Desktop chat    apps with embedded AI
  dashboards                                       C6 OpenAPI / MCP schemas
                                                   C7 serving table schemas

 ORCHESTRATION · Dagster runs every box as assets, with checks, schedules and sensors
 DEVOPS · GitHub Actions CI/CD, Bicep IaC, dev → test → prod
 OPERATIONS · Dagster alerts + Azure Monitor; cost by component from tagged resources
 GOVERNANCE · owners required, dbt docs catalog, lineage from source table to dashboard tile
```

### Components

The rows marked "added" are components the brief left implicit, which the
platform needs anyway.

| Component | Baseline | What it does here | Writes (its contract) |
|---|---|---|---|
| Cloud infrastructure | Azure, Bicep | Resource groups per env, storage, Key Vault, Container Apps, Postgres, monitoring | `infra/` modules |
| Master data management | Splink, with a rules-based SQL matcher as the comparison provider | Matches customer, item, supplier and employee records across systems | C3 xref and golden tables |
| Orchestration | Dagster | One asset graph from source table to dashboard export | Run history, asset checks |
| Ingestion | dlt | Extracts the three sources and the MDM provider, and writes bronze | C2 bronze changelog |
| Change data capture | dlt `sql_database` over SQL Server CDC change tables | Exact inserts, updates and deletes from X3 | `_op` and `_change_seq` on bronze rows |
| Raw storage | ADLS Gen2 (a local folder or Azurite on a laptop) | An append-only, replayable changelog | Parquet files, C2 layout |
| Transformation | dbt Core | bronze → silver → gold, tests, contracts, docs | C4 gold contracts |
| Warehouse storage | DuckDB file, published to ADLS after each run | The built warehouse | `warehouse.duckdb` |
| Compute | DuckDB | Runs dbt, MetricFlow queries and mart builds | — |
| Semantic modeling | dbt MetricFlow YAML | Measures, metrics, entities, saved queries | C5 semantic manifest |
| Visualization | Power BI | One generated model over one imported table, `dashboard_cube`, with templated measures; process, department and account reports | PBIP in git |
| Distribution | Power BI apps and subscriptions; data service | Puts dashboards and data in front of people and apps | — |
| Downstream apps | dlt reverse load into Postgres, plus the data service | App-serving tables and a governed API | C6, C7 |
| Applied AI | Claude Code and an MCP server over MetricFlow | Agentic chat, AI-built apps, embedded AI, and the team's own runbooks as skills | MCP tool schemas |
| *Added:* Data quality and observability | dbt tests, Dagster asset checks, freshness | Catches bad data before it reaches a dashboard | Check results, `ops` tables |
| *Added:* Catalog and lineage | dbt docs, exposures, Dagster asset graph | Ownership, definitions, lineage end to end | Hosted catalog |
| *Added:* Secrets and identity | Entra ID, managed identities, Key Vault | Workload and human access | — |
| *Added:* CI/CD and IaC | GitHub Actions, Bicep | Promotion across three environments | — |
| *Added:* Cost management | Azure tags, budgets, cost exports | Cost by component and environment, fed back through the platform | `fct_cloud_cost` |
| *Added:* Source simulation | Python simulators and a clock | Stands in for the three source systems | Mock DB and ground truth |

## 4. Contracts at component boundaries

Each contract is a file in git, carries a version, and is enforced by a test
that runs in CI. A breaking change bumps the version and needs the owner's
approval in review.

| # | Boundary | Contract | Enforced by |
|---|---|---|---|
| C1 | Source → ingestion | `ingestion/specs/<source>.yml`: tables, keys, strategy, cursor, notes | Resource builder fails on unknown strategy; review |
| C2 | Ingestion → bronze | `ingestion/schemas/<source>.schema.yaml` (frozen columns and types), plus one append-only table per source table at `bronze/<source>/<table>/` (Delta, partitioned by load date) with metadata columns `_load_id, _extracted_at, _op (I/U/D/S), _change_seq`. Any ingestion tool must deliver deletes, change history and the original column names (§9.3, rule 2). | dlt `schema_contract: {columns: freeze, data_type: freeze}`; ingestion conformance test |
| C3 | MDM → silver | `mdm/contract.yml`: `mdm_xref(domain, source_system, source_key, golden_key, match_score, match_rule, steward_status, valid_from)` and `mdm_golden_<domain>` | dbt source tests; MDM conformance test, which every provider must pass |
| C4 | Silver → gold | dbt model contracts (`contract: {enforced: true}`) on every gold model | `dbt build` fails on drift |
| C5 | Gold → semantic → consumers | MetricFlow YAML, the compiled `semantic_manifest.json`, and `metric_catalog.json` (definitions, governance, valid dimensions) | `mf validate-configs`, governance lint, golden answers |
| C6 | Semantic → apps and agents | The data service's OpenAPI spec and MCP tool schemas | API and MCP contract tests |
| C7 | Platform → serving DB and BI | One table per saved query, plus `dashboard_cube` stacking them all for Power BI | Cube tests (one row per grain, consistent ratios) and the Power BI parity queries |

Anything that wants to replace a component must produce its contract and pass
its test. §8 turns this into the evaluation kit, and §9 maps the other stack
options onto these contracts.

## 5. What happens to the current branch

Before pruning, tag the current state as `v1-prequel` so the v1 design stays
recoverable.

### Keep, and build on

- **The simulator seam** (`ingestion/simulators/`), extended with a clock and
  CDC (§7.1).
- **The X3, HubSpot and Netstock mock data and its landmines**: CHAR padding,
  1753 dates, archived records, name drift, Netstock orphans.
- **The extraction knowledge in `ingestion/config.py`.** Its notes move into
  the C1 spec files.
- **The X3 and HubSpot staging models.** They become hand-maintained, with
  two macros doing the cleaning.
- **`int_sales_order_line`, `int_sales_return_line`, `int_supplier_invoice_match`
  and `int_fx_rate`.**
- **The core dims and facts that don't depend on Pangea or Paycom.**
- **The invoice-to-GL reconciliation test** and the other singular tests.
- **`process.csv` and the "metrics are not owned by processes" mapping.**
- **The open questions**, pruned and extended (§12).
- **The docs' voice and the diagrams.**

### Cut

| What | Why |
|---|---|
| Paycom and Pangea: simulators, 11 staging models, `int_employee_xref`, `int_shipment_*`, `fct_shipment`, `fct_shipment_event`, `dim_carrier`, their metrics, seeds and docs | Out of scope. On-time delivery comes back from X3 deliveries (§7.5). |
| `scripts/compile_metrics.py`, `generate_process_views.py`, `test_metric_parity.py`, `ask_metric.py`, the `mtr_*` and `mart_*` models, the `metric_registry` seed | Replaced by MetricFlow, saved queries, golden answers and the MCP server. About 1,900 lines of custom code go. |
| `scripts/generate_staging.py` | 815 lines to generate about 40 simple files, and it depends on a `.cache_columns.json` that isn't in the repo. Keep the generated SQL as plain files. |
| `ingestion/contract.py`, `scripts/freeze_schema_contract.py`, `schema_contract.json` | dlt's native schema contracts and schema import/export do the same job. |
| The projection in `ingestion/pipeline.py`, and `raw.duckdb` | Bronze current state becomes a dbt macro reading Parquet directly, which removes a stage and a database file. |
| `scripts/q.py`, `verify_ingestion.py`, `profile_sources.py`, `_toolchain.py`, `regenerate.py`, `run_ingestion.py` | Replaced by the DuckDB UI, the conformance tests, Dagster and the Makefile. |
| dbt snapshots | The CDC changelog in bronze keeps every version, so as-was history can be built from bronze whenever it is needed. Open question 11 stops being a cost that grows every day. |
| `mock_sources.duckdb` in git | Regeneration takes about 1.3 seconds and produces a different 17 MB binary each time, so every regeneration is a 17 MB diff in history. Generate it on setup instead. |

### Change

| What | To |
|---|---|
| Custom metric YAML (`semantic/metrics/*.yml`) | MetricFlow semantic models and metrics. Governance fields move into `config.meta`. Placeholder and blocked metrics move to `semantic/backlog.yml`, because MetricFlow cannot hold a metric with no definition. |
| `scripts/export_powerbi.py` | No DAX translation (D12). Power BI imports one table of saved-query results, and a small generator writes a model with one templated measure per KPI. |
| `int_customer_xref` (four SQL probes) | Two MDM providers writing C3: Splink, and the four probes ported into `mdm/rules_provider.py` as the comparison. Both are scored against the generator's ground truth. |
| `requirements*.txt` | `pyproject.toml` and `uv.lock`. |
| Folder layout | One folder per component (§6), each with a README stating its contract and how to swap it. |

## 6. Target repo layout

```
README.md  PLAN.md  CLAUDE.md  Makefile  pyproject.toml  uv.lock  .env.example
config/            local.yaml dev.yaml test.yaml prod.yaml   (PLATFORM_ENV picks one)
sources/           synthetic source systems
  generate.py        deterministic generator: X3, HubSpot, Netstock, ground truth
  clock.py           as-of dates, day-by-day change simulation, X3 CDC change tables
  simulators/        sage_x3.py  hubspot.py  netstock.py
ingestion/         dlt pipelines built from a pack's specs (C1) and frozen schemas (C2)
mdm/               contract.yml (C3); splink_provider.py; rules_provider.py
core/              settings, project.py (the pack in use and its paths), pack.py (check-pack)
transform/
  profiles.yml       the connection, shared by every pack
  platform/          dbt package: macros, staging adapters per source system,
                     project_template.yml (every pack's dbt_project.yml)
projects/<slug>/   a project pack: content only, no Python (v3)
  project.yml        name, systems, MDM provider, pinned architecture version
  scenario.yml       the synthetic data's settings
  ingestion/         specs/*.yml (C1); schemas/*.schema.yaml (C2)
  models/bronze/     current state from the changelog (one macro call per table)
  models/silver/     intermediate + conformed entities
  models/gold/       star schema with enforced contracts (C4)
  models/semantic/   MetricFlow semantic models, metrics, saved queries, time spine (C5)
  seeds/ tests/      process, department, process_metric, department_metric, crosswalks
  backlog.yml        placeholder and blocked metrics
  golden_answers.yml
  powerbi/ docs/     generated model and catalogue; open questions, source quirks
semantic/          catalog generator, governance lint, rollups
serving/           semantic_service (DuckDB and T-SQL backends), cube materializer,
                   Power BI model generator, reverse loads
apps/
  data_service/      FastAPI: REST + MCP over the semantic layer and the serving DB (C6)
  examples/ask_metrics/  embedded-AI example app
orchestration/     Dagster definitions: assets, checks, schedules, sensors
infra/             Bicep: main.bicep, modules/, env/*.bicepparam
evaluation/        component registry, scorecard template, golden-answer harness, cost model
tests/             pytest: unit, conformance, end-to-end
docs/              architecture, components/*.md, running, adding a metric, open questions
.github/           workflows/, CODEOWNERS, pull_request_template.md
.claude/skills/    add-metric, add-source-table, swap-component, run-the-platform
```

`make setup`, `make mock`, `make run` (the full pipeline through Dagster),
`make test`, `make docs` and `make ui` (Dagster plus the DuckDB UI) are the
whole interface a client needs to see.

## 7. Design by area

### 7.1 Synthetic sources and the clock

- **Three systems.** Remove Paycom and Pangea from the generator.
- **New X3 tables, so delivery and department metrics exist.** Add
  `SDELIVERY` and `SDELIVERYD` (deliveries) and `AUTILIS` (X3 users, with
  email). Keep `CREUSR_0` on documents. Verify the table names against the
  client's folder, as the current docs already ask for the other X3 tables.
- **Ground truth.** The generator also writes `truth.*` tables: the real
  identity behind every customer, item and employee record, and the real
  department of every user. They are the answer key MDM providers are scored
  against. Nothing in the pipeline reads them.
- **A clock.** Generate the full timeline once, through the end of the POC
  window, with valid-from, valid-to and deleted-at columns. Then
  `clock.as_of(date)` gives any day's source state, and
  `make advance DAYS=n` moves the simulators forward. Each day carries new
  orders, status changes, deliveries, invoices getting paid (the
  business-date-window trap), late returns, PO receipts, HubSpot stage moves
  and archivals, X3 hard deletes and a Netstock resync.
- **X3 CDC change tables.** Shape them like SQL Server's
  (`cdc.dbo_<TABLE>_CT` with `__$start_lsn`, `__$seqval`, `__$operation`
  1/2/3/4, `__$update_mask`), derived by diffing consecutive days. The
  production swap points the same dlt resource at the real change tables.
- **Optional fidelity upgrade:** a `docker compose --profile sqlserver`
  running SQL Server 2022 Developer with CDC turned on, loaded from the
  existing `schema.sql`. That runs the production code path with no
  simulator at all. On Apple Silicon it runs under emulation, so it is opt-in.
  It reuses the SQL Server container the T-SQL test already runs (§7.6).

### 7.2 Ingestion, change data capture and raw storage

There are three sources and three patterns:

| Source | Incremental mechanism | Deletes | Fallback |
|---|---|---|---|
| Sage X3 | CDC change tables, cursor on LSN, via open-source dlt `sql_database`. One initial snapshot, then changes from the LSN captured at the start of the snapshot. | `__$operation = 1` lands as `_op = 'D'` | dltHub's commercial Change Tracking connector, or v1's header-window plus weekly key reconciliation |
| HubSpot | `hs_lastmodifieddate` / `lastmodifieddate` cursor with a lookback; an archived second pass; associations as a full crawl | Archived flag, plus a weekly key reconciliation for hard deletes | — |
| Netstock | Snapshot replace, skipped when `last_sync_at` hasn't moved | Implicit, because the snapshot replaces | — |

- **Bronze is an append-only changelog in ADLS, stored as Delta tables**
  (Parquet files plus a transaction log), laid out as C2. It is replayable
  and auditable. Delta rather than plain Parquet because a Fabric Lakehouse
  reads Delta folders as tables through a OneLake shortcut, DuckDB reads them
  with its delta extension, and the transaction log means a reader never
  sees a half-written load. Plain Parquet is the fallback if the Phase 0
  spike fails (D3).
- **dlt pipeline state lives with the destination**, so a container can be
  replaced without losing watermarks.
- **CDC retention is the main pitfall.** SQL Server keeps change data for 3
  days by default. An outage longer than retention has to trigger a fresh
  snapshot automatically, not leave a silent gap. Build that, and test it with
  the clock.
- **Ingestion conformance test:** backfill on day 0, then advance N days.
  Bronze current state must equal the source as-of state exactly, deletes
  included, and each incremental run must read only the changed rows.

### 7.3 Master data management

- **Open source only.** The client is leaning towards Boomi Data Hub, but the POC
  builds no Boomi code. MDM here is a placeholder made of open-source
  providers. Contract C3 states what any MDM has to produce, whether that is
  Boomi or another product, and the conformance test is how it gets judged.
  The providers write C3 into the `mdm/` area of raw storage, where an
  external MDM's export would land, and silver reads it only through
  `source('mdm', …)`. Whichever product is chosen replaces the provider, and
  nothing downstream changes.
- **Splink is the main provider.** It runs as a Dagster asset on DuckDB,
  which is Splink's native backend, reading silver staging and writing C3. It
  covers:
  - customers: X3 BPCUSTOMER ↔ HubSpot company, matched on names, domains and
    the legal-suffix seed
  - employees: X3 AUTILIS and REPRESENT ↔ HubSpot owners, matched on email,
    then name
  - items and suppliers: X3 ↔ Netstock, mostly on exact keys
- **A rules matcher is the comparison provider.** v1's four deterministic
  probes in `int_customer_xref` move into `mdm/rules_provider.py` and write
  the same C3 tables. Most commercial MDM tools match by rules, so putting a
  rules matcher next to Splink's probabilistic matching, both scored against
  ground truth, is a real comparison of two approaches. It is also cheap,
  because the probes already exist.
- **One setting switches provider:** `MDM_PROVIDER=splink|rules`. That switch
  is the first swap drill (§8).
- **Operational MDM is out of scope.** Syncing golden records back into X3
  and HubSpot is something the chosen MDM product must do, so it goes in the
  component doc as a requirement for candidates. The POC doesn't build it.
- **Match quality is a published metric:** precision and recall against
  ground truth for evaluation, and the unmatched rate as a governance metric,
  as in v1.

### 7.4 Transformation and warehouse

- **dbt-duckdb reads bronze as external sources** (`external_location` on
  ADLS or a local path).
- **One macro, `bronze_current(source, table, keys, kind)`,** turns the
  changelog into current state: the latest row per key by `_change_seq`,
  tombstones dropped, snapshots taken from the newest `_load_id`. It replaces
  `pipeline.py`'s projection.
- **Layers:** `bronze` (current state), `silver` (staging cleanup through
  `x3_key()` and `x3_date()` macros, plus conformed entities joined through
  C3), `gold` (the star, enforced contracts, `meta.owner` on every model).
- **Incremental models: start with a full rebuild from bronze on every run.**
  At this volume it is fast, deterministic and idempotent. The requirement
  is incremental refresh *from the sources*, and that happens at ingestion.
  One large fact gets an incremental model as the pattern to copy at scale.
- **Publish the warehouse file.** After each run the DuckDB file goes to
  `adls://warehouse/<env>/warehouse.duckdb`, versioned by run ID, and
  read-only consumers (the data service) pick it up from there.
- **Vars still carry the business assumptions:** fiscal start month,
  tolerances, currency.

### 7.5 Data model (gold), processes and departments

**Proposed star.** Only facts a metric needs, as in v1.

| Dimensions | Facts |
|---|---|
| `dim_date` (fiscal periods, also used as MetricFlow custom granularity) | `fct_sales_order_line` (X3) |
| `dim_customer` (MDM golden) | `fct_delivery_line` (X3 SDELIVERYD), new; replaces Pangea for on-time delivery |
| `dim_item` (X3 + Netstock planning attributes) | `fct_invoice_line` (X3, reconciles to GL 41000) |
| `dim_site` | `fct_supplier_invoice_line` (X3, three-way match) |
| `dim_supplier` (X3 + Netstock), new | `fct_inventory_count_line` (X3) |
| `dim_employee` (MDM golden; carries department), new | `fct_deal` (HubSpot, accumulating snapshot of stage dates), new |
| `dim_department`, new | `fct_forecast_accuracy` (Netstock item × location × period), new |

**The process × department matrix.** Two separate ideas, kept apart:

1. **Relevance** (metadata, in seeds):
   - `process.csv` and `department.csv` list the two axes.
   - `process_metric.csv` (process, metric, slot) says which metrics appear
     on each process dashboard.
   - `department_metric.csv` (department, process, metric, owns or
     contributes) says which metrics in which process each department
     influences.
   - Relationship tests tie both mapping seeds to the metric catalog, so a
     typo fails the build. A metric appears on many dashboards as rows in a
     seed, never as copies of its definition.
2. **Attribution** (data): department is a dimension, reached through the
   person who did the work. X3 documents carry `CREUSR_0` → `dim_employee` →
   department. HubSpot deals carry the owner → `dim_employee` → department.
   Through MetricFlow, any metric whose fact has a performed-by key can be cut
   by department, and the rest are refused.

A department dashboard shows the metrics its seed rows name. Where the metric
can be attributed, the tile shows the department's own slice of the activity.
Where it can't, the tile shows the company-wide value and says it is not
attributable. That flag is generated from MetricFlow's list of valid
dimensions, never written by hand. The departments and the mappings below are
illustrative placeholders until the business defines them (open question
Q-A).

**Initial metrics.** These are placeholders where the business hasn't decided,
so the design gets exercised.

| Metric | MetricFlow type | Fact | Status |
|---|---|---|---|
| On-Time Delivery (against the requested date) | ratio | `fct_delivery_line` | provisional: promise basis |
| Order Fill Rate | ratio | `fct_delivery_line` | placeholder |
| Return Rate | ratio | `fct_sales_order_line` | provisional (from v1) |
| DSO, days-to-pay proxy | ratio | `fct_invoice_line` | provisional (from v1) |
| Unsettled Invoice Rate | ratio | `fct_invoice_line` | active (from v1) |
| Match Rate | ratio | `fct_supplier_invoice_line` | provisional (from v1) |
| Inventory Accuracy | ratio | `fct_inventory_count_line` | provisional (from v1) |
| Forecast Accuracy (1 − WMAPE) | derived | `fct_forecast_accuracy` | provisional |
| Win Rate, Pipeline Value, Sales Cycle Days | ratio, simple, ratio | `fct_deal` | placeholder |
| Trailing 90-day Revenue | cumulative | `fct_invoice_line` | placeholder; tests cumulative metrics |
| Customer Match Rate | ratio | MDM xref | active, data quality |
| Cost Per Shipment, Cost Per Order | — | — | blocked: no freight source. Lives in `backlog.yml`. |

### 7.6 Semantic layer

- **What lives in `models/semantic/`:** one semantic model per fact and per
  dimension, with entities, dimensions and measures; metrics; saved queries;
  and a time spine with custom fiscal granularity. Pin `dbt-core`,
  `dbt-duckdb` and `dbt-metricflow` together.
- **"Any valid dimension combination and grain"** is MetricFlow's core job:
  `group_by` any dimension reachable through the entity graph, `metric_time`
  at day, week, month or quarter (fiscal included). Invalid combinations are
  refused with a reason. Every query computes from the base fact. The one
  place pre-aggregated rows are re-aggregated is Power BI over the cube, and
  there the measure templates and their guards rule out v1's bug class
  (distinct counts summed across pre-aggregated views): D12, §7.7.
- **Governance metadata lives in `config.meta`:** `status`
  (active | provisional | placeholder | blocked), `owner`, `owner_proposed`,
  `provisional_reason`, `caveats`, `format`, `direction`. A lint script over
  the manifest enforces the same rules v1's compiler did: a required owner
  field, a reason for every non-active status, measures that aggregate a bare
  column (arithmetic goes in the fact), and every KPI in at least one saved
  query so a dashboard can show it.
- **How a metric rolls up is derived, not declared** (`semantic/rollup.py`):
  `sum` (sums and counts), `ratio` (a ratio of two sums, with no filter on
  the ratio itself; put filters on the components), or `fixed` (everything
  else: distinct counts, averages, derived and cumulative metrics). It decides
  which ratio components a cube stores and which measure template Power BI
  gets.
- **Track Ossie.** Apache Ossie (incubating) has a dbt converter and a
  Microsoft-contributed Power BI converter. dbt 1.12 already writes the
  definitions in that format (`osi_document.json`). It matters if the client
  later wants Power BI as a query engine of its own; the cube route (D12)
  doesn't need it.
- **Backlog and catalog.** `semantic/backlog.yml` holds placeholder and
  blocked metrics with the same governance fields. The catalog generator
  merges manifest + backlog + seeds into `metric_catalog.json` and
  `docs/metric_catalog.md`.
- **One metric query service** (`serving/semantic_service.py`):
  `list_metrics`, `describe_metric`, `valid_dimensions(metrics)`,
  `compile(...)` and `query(...)`, built on MetricFlow's Python API. The MCP
  server, the REST API, the mart materializer and the tests all call it, and
  nothing else imports MetricFlow. Swapping the semantic engine means
  reimplementing this one module.
- **A T-SQL path, so MetricFlow survives a Microsoft warehouse.** MetricFlow
  has no T-SQL renderer (§9.1), so `semantic_service` gets a second backend:
  - MetricFlow renders each query as Postgres-style SQL.
  - sqlglot translates it to T-SQL.
  - pyodbc runs it.

  Consumers don't notice, because they only call `semantic_service`. This is
  not a second stack. The only T-SQL engine in the repo is a SQL Server 2022
  container in CI, loaded with a copy of gold through dlt's SQL Server
  destination. The golden answers have to come back the same through it.
  Where sqlglot can't translate something (percentiles and some date
  functions are the likely gaps), the test names the metric, and that metric
  becomes a known limit for a T-SQL warehouse.

### 7.7 The five downstream routes from one definition

| Use case | Route | Computes with |
|---|---|---|
| Dashboards | Power BI imports one table, `marts.dashboard_cube`: every saved query's results stacked, with a `_cube` column, shared dimension columns, and the numerator and denominator of every ratio. Parquet from ADLS, no gateway needed. A generated model gives each KPI one measure from three guarded templates: `SUM`, `DIVIDE(SUM, SUM)`, or a single-row value for fixed metrics. Reports are hand-built PBIP, presentation only, each page or visual filtered to one cube. | MetricFlow SQL at fixed grains; Power BI only sums and divides |
| Denormalized marts | The same saved queries: one per process page, one per department and account view, one company-wide. The materializer compiles each through MetricFlow into DuckDB tables and Parquet. dbt Cloud runs saved-query exports natively, and in dbt Core this small script does it. | MetricFlow SQL |
| Agentic AI chat | An MCP server inside the data service, with tools `list_metrics`, `describe_metric`, `valid_dimensions`, `query_metrics`, `explain_sql`. Answers carry the caveats and status; blocked or placeholder metrics return no number. Locally it is set up in `.mcp.json` for Claude Code; hosted, it is Streamable HTTP behind Entra auth. | MetricFlow at query time |
| Apps built with AI coding tools | REST endpoints on the same service (`/metrics`, `/query`, `/datasets/{saved_query}`) with an OpenAPI spec, served from Postgres for low latency. Plus an `AGENTS.md` and a Claude Code skill telling a coding agent how to use them. | MetricFlow and the serving DB |
| Apps with embedded AI | `apps/examples/ask_metrics`: a small app that calls the Claude API with the MCP tools, so the agent only ever reaches governed metrics. | MetricFlow at query time |

- **Parity across routes is tested** with the golden answers in §8. Each
  golden answer a cube can serve becomes a DAX query. Locally and in CI, the
  templates' SQL twin runs those queries over the cube. In test, the same DAX
  runs through the Power BI REST `executeQueries` API against the deployed
  model, which closes the "L4 manual" gap v1 left open.
- **Why the guards make dashboards safe.** A sum or ratio is blank unless a
  visual is filtered to one cube, so rows from two cubes never add up; within
  a cube it rolls up correctly to any coarser grain, totals included. A fixed
  metric shows only where a visual lands on exactly one stored row, so a
  total or an unsupported grain is blank, never an average of averages. A
  report mistake can produce a blank, not a wrong number.
- **A stretch reverse-ETL example:** push customer KPIs into HubSpot company
  properties through the HubSpot simulator's write endpoint. That shows
  data flowing back to a source app.

### 7.8 Orchestration

- **Assets:**
  - `dagster-dlt` assets, one per source table
  - MDM assets for the selected provider
  - `dagster-dbt` assets for bronze, silver and gold, with dbt tests as
    asset checks
  - a semantic validation check
  - saved-query cubes, stacked into `dashboard_cube`
  - the Power BI refresh call
  - the Postgres reverse loads
  - warehouse publish
  - the cost-export ingest
- **Thin by rule.** Each asset calls a step command that also runs without
  Dagster, and data quality checks live in dbt (§9.3, rule 1). ADF, a Boomi
  Logic Flow or Snowflake Tasks could replace Dagster without any logic
  moving.
- **Jobs:** `daily` (incremental), `weekly_reconcile` (HubSpot key diffs),
  `cdc_resnapshot` (manual, or triggered when retention is exceeded).
- **Sensors:** run failure → Teams or email; freshness checks on each bronze
  table.
- **Local:** `dagster dev` is the runner.
- **Azure:** one Container App (webserver + daemon, in-process run launcher
  at this scale) with Postgres for run storage.

### 7.9 Environments, CI/CD, code review and testing

- **Environments:**
  - **local:** laptop, filesystem or Azurite, mocks.
  - **dev:** Azure, mocks, the integration env, deployed on every merge.
  - **test:** Azure, mocks plus golden answers plus a Power BI test
    workspace, promoted with approval.
  - **prod:** Azure, live connectors, promoted with approval.

  All four are defined from day one. Dev is stood up during the POC, test and
  prod when needed, to keep cost down. `PLATFORM_ENV` selects
  `config/<env>.yaml` and the dbt target. Live versus mock is just
  `SOURCE_MODE`.
- **Version control and review:**
  - Trunk-based, with short-lived branches and pull requests into `main`.
  - Branch protection: one review and green CI.
  - CODEOWNERS:
    - `transform/models/semantic/` → the data lead, plus each metric's owner
      once one is assigned
    - `infra/` → platform
    - `ingestion/` and `mdm/` → data engineering
  - The PR template asks about contract changes, metric value changes and
    whether golden answers changed.
  - Optional: Claude code review as a PR check.
- **Testing pyramid:**
  - **unit** (pytest): simulators, the CDC diff, the rollup classification
    and measure templates, the catalog, MCP tools
  - **data** (dbt): schema, relationship and contract tests, singular
    reconciliations, dbt unit tests for the matching and three-way-match SQL
  - **conformance:** C1–C7, golden answers, and the golden answers through
    the cube
  - **end to end:** the full pipeline on mocks
  - **post-deploy:** a smoke run in dev, Power BI parity in test
- **CI on every PR** (GitHub Actions; Azure DevOps is a drop-in if that is
  the client's standard):
  - ruff
  - pytest
  - `dbt parse` and `mf validate-configs`
  - the governance lint
  - generated-artifacts-current check
  - the full pipeline on mocks, for several simulated days, plus golden
    answers. It runs through the step commands without Dagster, which proves
    rule 1 in §9.3.
  - the SQL portability check: every compiled silver and gold model
    transpiled to T-SQL and Snowflake SQL with sqlglot (§9.3, rule 3)
  - the Ossie export of the semantic definitions (§9.3, rule 5)
  - the T-SQL compatibility test: gold copied into a SQL Server 2022
    container, and the golden answers run through the T-SQL path (§7.6).
    GitHub's Linux runners run the container natively.
  - the blocked-word check, with the word list held in a CI secret (§2,
    principle 6)
  - gitleaks
  - Bicep lint and what-if
- **CD on merge:**
  1. Build the image and push it to the registry.
  2. Deploy to dev and run a smoke pipeline.
  3. A GitHub Environment approval gates test, then prod.
  4. The Power BI model deploys from TMDL to the matching workspace, and the
     parity queries run against it in test. The deployment method depends on
     licensing (open question Q-D).

### 7.10 Operations: monitoring, alerting and cost

- **Monitoring:**
  - Dagster's UI is the operations console.
  - Asset checks with error severity raise alerts.
  - Container Apps logs go to Log Analytics, with alert rules on failed runs,
    restarts and Postgres health.
  - A small `ops` schema records rows extracted per table per run, freshness
    lag and test failures, feeding a Platform Health page in Power BI.
- **Cost tracking:**
  - Every resource is tagged `env`, `component` (using the names in §3),
    `stack=oss-baseline` and `owner`.
  - Budgets per resource group alert at 50, 80 and 100%.
  - A daily Cost Management export in FOCUS format lands in ADLS. The
    platform ingests it like any other source, into `fct_cloud_cost`, and a
    Platform Cost page shows cost by component and environment.
  - A `license_cost.csv` seed adds per-user and per-capacity SaaS costs
    (Power BI and any commercial candidate), so the evaluation compares total
    cost of ownership, not just the Azure bill.

### 7.11 Security

- **Identity:** Entra ID for people. User-assigned managed identities for
  workloads, scoped to specific storage containers and Key Vault. Storage
  shared-key access is turned off.
- **Secrets:** Key Vault per environment, referenced from Container Apps.
  Locally, a `.env` file (with `.env.example` committed). dlt reads
  credentials from environment variables. CI runs secret scanning, with push
  protection on.
- **Data access by layer:**
  - bronze and silver: engineers only
  - gold and marts: analysts, through Power BI
  - data service: app identities, with Entra-issued tokens
- **PII:** columns are tagged `meta.pii` in dbt (for example HubSpot contact
  email and phone) and kept out of gold. Because PII never becomes a
  semantic dimension, the API and MCP server cannot return it.
- **AI guardrails:** the MCP server and API are read-only, limited to
  governed metrics, with row limits and timeouts, and every AI query is
  logged with who asked, what, and when.
- **Network:** public endpoints with firewall rules for the POC. Production
  gets private endpoints, VNet integration, and a route to X3 over VPN or
  ExpressRoute, or a self-hosted runner if X3 is on-premises (open question
  Q-C).
- **Record the gaps honestly.** DuckDB has no user-level security, so access
  control lives in storage and the API. That is a real point to weigh in the
  evaluation, not something to hide.

### 7.12 Governance

- **Ownership:** `meta.owner` is required on every source, gold model and
  metric, and a CI check enforces it. `TBD` is allowed but visible, as in v1.
- **Catalog:** dbt docs (models, columns, tests, metrics, saved queries,
  exposures) built per environment and hosted on Azure Static Web Apps behind
  Entra sign-in, alongside the generated metric catalog. Microsoft Purview,
  OpenMetadata and DataHub are evaluation candidates.
- **Lineage:** dbt `exposures` for every dashboard, mart, the data service
  and the Postgres tables. Together with Dagster's asset graph, that gives
  lineage from an X3 table to a dashboard tile.
- **Change control:** metric definitions change only through a PR approved
  by CODEOWNERS. A golden-answer diff makes any change to a number visible in
  review.

### 7.13 Azure infrastructure

Written in Bicep, as `infra/main.bicep` plus modules, with one `.bicepparam`
per environment.

- **Per environment:**
  - a resource group
  - an ADLS Gen2 storage account with containers `bronze`, `warehouse`,
    `exports`, `costs` and `$web`
  - Key Vault
  - Log Analytics and Application Insights
  - a Container Apps environment with two apps, `dagster` and
    `data-service`
  - PostgreSQL Flexible Server on the Burstable tier, holding Dagster storage
    and the serving DB
  - a user-assigned managed identity with role assignments
  - an action group and budgets
  - a Static Web App for the catalog
- **Container registry:** GHCR (free) or ACR Basic.
- **Expected cost:** the always-on footprint is one small container plus a
  burstable Postgres. That points to a low-hundreds-of-dollars-a-month dev
  environment. The tagged cost data will show the real figure, which is the
  point of tagging.

## 8. The evaluation kit

This is what turns the baseline into a tool for choosing software.

1. **A component registry** (`evaluation/components.yml`). For each component
   it records:
   - the requirements and best practices the component serves
   - its contract (C1–C7)
   - the baseline implementation and how to swap it out
   - candidate alternatives

   The registry starts with the three other columns from the stack menu
   (the client's existing stack, Mix 1 and Mix 2), mapped in §9. These candidates
   aren't on the menu yet and are worth a row:

   | Component | Candidates not on the menu |
   |---|---|
   | Ingestion | Airbyte |
   | Orchestration | Dagster+ |
   | Warehouse and compute | Databricks, MotherDuck |
   | Semantic modeling | dbt Cloud Semantic Layer, Cube, AtScale (all three connect to Power BI live); the Boring Semantic Layer (open source) |
   | Applied AI | Fabric data agents or Copilot, Databricks Genie |

2. **Conformance tests**, one per contract: ingestion convergence, MDM match
   quality, gold contracts, golden answers, API and MCP contracts. A
   candidate passes if it produces the same contract outputs from the same
   synthetic sources.
3. **Golden answers** (`evaluation/golden_answers.yml`): about 40 fixed
   queries (metric × dimensions × grain × filter) with the expected values
   computed from the synthetic data, plus a few that must be refused. Any
   semantic engine and any BI tool must reproduce them. That turns "does
   Cube or a Fabric semantic model give the same numbers?" into a test run.
4. **A scorecard template** (`evaluation/scorecard.md`) scoring each
   candidate on:
   - requirement coverage (low-code fit for a lean team, incremental refresh,
     governed measures feeding the five routes)
   - best-practice support
   - cost (licence + Azure + people)
   - portability and lock-in
   - maturity
5. **Cost capture** through the tags and cost exports in §7.10, so
   comparisons use measured cost.
6. **Swap drills.** These prove the modularity claims instead of asserting
   them:
   - **Drill 1** (in scope): the MDM provider, Splink ↔ the rules matcher,
     with config only. Both are scored against ground truth.
   - **Drill 2** (stretch): the warehouse engine, DuckDB → Postgres with
     dbt-postgres, which MetricFlow also supports. It is free, and it shows
     the SQL and the semantic layer moving between engines.
   - **Drill 3** (local in CI, remote ready): the BI consumer. The golden
     answers a cube can serve run through the cube and the measure templates,
     locally as SQL and against the deployed model as DAX.
   - **Drill 4** (stretch): the semantic engine, MetricFlow ↔ the Boring
     Semantic Layer. Define the same metrics over the same gold tables, run
     the golden answers through both, and compare its built-in MCP server
     with ours. That tests whether a lighter, AI-first semantic layer does
     better for the AI routes, and the Boring Semantic Layer's Ibis base also
     reaches SQL Server, which MetricFlow doesn't.

## 9. Compatibility with the other stack options

The stack menu has three more columns: the client's existing stack, Mix 1 (Boomi +
Microsoft Fabric) and Mix 2 (Snowflake + Fivetran). The final stack will
probably combine cells from all of them, plus tools not on the menu yet.
**None of them is built in this repo.** This section records where each one
would plug in, what a swap costs, and the rules the baseline follows so swaps
stay cheap.

### 9.1 What it is fair to promise

> Every component sits behind a written contract with an automated test.
> Swapping a component means re-implementing one box and passing the same
> tests. It does not mean rebuilding the platform.

That is defensible. "Swap anything, anytime, for free" is not. Swaps differ a
lot in cost, and two pairs of components are coupled:

- **Warehouse ↔ semantic layer.** MetricFlow is a SQL compiler: it writes
  each query in the warehouse's own SQL dialect and sends it there to run.
  It has renderers for Snowflake, BigQuery, Databricks, Redshift, Postgres,
  DuckDB, Trino, Athena, ClickHouse and Vertica. It has none for T-SQL,
  which is the dialect of Azure SQL MI and Fabric Warehouse.
  - **If either of those holds gold,** the routes that query through
    MetricFlow (marts, the data service, AI chat and apps, the golden
    answers) have nothing to run on.
  - **The Power BI route follows MetricFlow,** because MetricFlow computes the
    cube Power BI imports. Whatever keeps MetricFlow running on a T-SQL
    warehouse keeps Power BI fed.
  - **The ways out:**
    - let MetricFlow write Postgres-style SQL and translate it to T-SQL with
      sqlglot. This plan builds that path and tests it in CI (§7.6), so it is
      the first one to try.
    - make the Power BI semantic model the query engine for every route,
      which is what the existing stack and Mix 1 already assume
    - point a MetricFlow-supported engine such as DuckDB at the Delta files
      Fabric keeps in OneLake (needs a test)
    - use a semantic layer that speaks T-SQL (the Boring Semantic Layer
      reaches SQL Server through Ibis; Fabric is unverified)
- **Transformation ↔ dbt.** dbt runs on all three alternative engines
  (dbt-sqlserver, dbt-fabric, dbt Projects on Snowflake). Leaving dbt for
  stored procedures or notebooks is a rewrite, and the tests, docs, contracts
  and lineage go with it. Keeping dbt in whatever final mix is chosen is the
  single biggest thing that keeps the promise true.

The swap costs in the table below:

- **Adapter:** configuration plus a thin adapter. Days.
- **Port:** the same logic on a new engine or dialect. Weeks.
- **Rebuild:** the logic re-expressed in another tool and re-verified with
  the golden answers. The biggest swap on this platform.

### 9.2 Component by component

| Component | Existing | Mix 1 | Mix 2 | Plugs in at | Swap cost | What has to hold |
|---|---|---|---|---|---|---|
| Cloud infrastructure | Azure | Azure | Azure | `infra/` modules | — | One Bicep module per component, so a managed service replaces one module |
| Master data management | Boomi Data Hub | Boomi Data Hub | Profisee | C3 | Adapter, plus an operating change: the product runs outside the pipeline and is fed by the source systems | It exports golden IDs and source cross-references, and the platform ingests them like any other source (rule 4) |
| Orchestration | ADF | Boomi DI Logic Flow | Fivetran schedules + Snowflake Tasks | Step commands | Adapter | No logic lives in Dagster (rule 1) |
| Ingestion | ADF | Boomi DI source-to-target flows | Fivetran | C1, C2 | Adapter: one bronze adapter macro per tool | Captures deletes, keeps change history, keeps source column names (rule 2). Netstock probably needs a custom connector in every column; check each catalog |
| Change data capture | ADF | Boomi DI SQL Server CDC | Fivetran Change Tracking or CDC connector | C2 | Adapter | Every column needs CDC or Change Tracking enabled on X3 (Q-C). Soft-delete flags such as `_fivetran_deleted` map to `_op = 'D'` |
| Transformation | ADF, pure SQL | Microsoft Fabric | Snowflake SQL or dbt Projects on Snowflake | C4 | Port if it stays dbt; rebuild if it doesn't | Portable SQL (rule 3) |
| Raw storage | Azure SQL MI | OneLake Lakehouse | Snowflake or ADLS | C2 | Adapter for OneLake (a shortcut to the ADLS bronze, no copy) and for ADLS; port for SQL MI or Snowflake tables | An open format in ADLS. Delta lets Fabric read the folders as tables (D3) |
| Warehouse storage | Azure SQL MI | Fabric Warehouse | Snowflake | C4 | Port | A dbt adapter plus portable SQL. DuckDB-specific code stays in bronze. On SQL MI or Fabric, MetricFlow follows through the T-SQL path (§7.6) |
| Compute | Azure SQL MI | Fabric capacity | Snowflake | C4 | Port, together with warehouse storage | As above |
| Semantic modeling | Power BI semantic models | Meta Hub glossary + Power BI semantic models | Snowflake Semantic Views | C5, C6 | Rebuild of the definitions (the Ossie converters may cut that down) plus a new `semantic_service` backend. Consumers don't change | Consumers only call C6 (rule 5). Coupled to the warehouse choice (§9.1). Meta Hub, a business glossary, takes the catalog export (rule 7) |
| Visualization | Power BI | Power BI | Power BI | C7 (`dashboard_cube`) | Adapter: switch the one load function to Fabric, SQL MI or Snowflake | The model holds no logic and doesn't depend on the source (rule 6) |
| Distribution | Power BI | Power BI | Power BI | — | — | — |
| Downstream apps | — | Boomi Integration | Snowflake Postgres | C6, C7 | Adapter | Plain Postgres, so Snowflake Postgres or Azure Postgres drops in. Boomi Integration reads the C7 tables or calls the C6 API |
| Applied AI | — | Boomi agent suite | Snowflake Cortex and/or Claude Code | C6 (MCP) | Adapter for any agent platform that speaks MCP. Cortex Analyst grounds on Snowflake semantic views, so it follows the semantic-layer swap | Standard MCP and an exportable catalog (rule 7) |

### 9.3 Rules the baseline follows so swaps stay cheap

1. **Orchestration stays thin.** Every step is a command that runs on its own
   (`make ingest SOURCE=sage_x3`, `dbt build`, `python -m mdm.run`,
   `python -m serving.materialize`), and Dagster only calls them. Data quality
   checks live in dbt (tests, `dbt source freshness`), not in Dagster-only
   checks. CI runs the pipeline through the commands without Dagster, which
   proves it.
2. **Silver reads one standard bronze shape.** That means source table and
   column names unchanged, plus `_is_deleted`, `_loaded_at` and
   `_change_seq`. dlt gets an adapter macro now, another ingestion tool gets
   its own macro later, and silver never notices. C2 lists what any ingestion
   tool must deliver: deletes, change history (append-only, or a history mode
   like Fivetran's) and the original column names. Without change history,
   as-was reporting is lost (§5, snapshots).
3. **Silver and gold SQL is portable.**
   - Use dbt cross-database macros instead of engine-specific functions.
   - Don't use `QUALIFY`, `EXCLUDE`, `GROUP BY ALL`, `::` casts, lateral
     column aliases, list or struct functions, or DuckDB-only date parsing.
   - Compare booleans explicitly, because T-SQL has no boolean type.
   - Leave source identifiers unquoted, so case rules don't bite.
   - Keep engine-specific SQL in bronze and in dispatched macros only.

   CI enforces this by transpiling every compiled silver and gold model with
   sqlglot to T-SQL and Snowflake SQL, failing on anything unsupported. That
   needs no adapter and no account.
4. **MDM output lands like an external system's.** Splink and the rules
   matcher write C3 into the `mdm/` area of raw storage, and silver reads it
   as a source. Only the golden key and the cross-reference are required, so
   a product with no match score still fits.
5. **Consumers depend on C6, never on MetricFlow.** The MCP tools, REST
   endpoints, mart materializer and tests all go through `semantic_service`.
   dbt also writes the definitions in the Open Semantic Interchange format on
   every parse, the starting point for translating them to Power BI or
   Snowflake semantic views if either becomes the engine.
6. **The Power BI model doesn't depend on its source.** Its one table loads
   through one M function (Parquet in ADLS today), and measures never
   reference the source. Reports bind only to the semantic model, so they
   survive any of the swaps above. Because the model holds no logic, another
   BI tool that can sum and divide could read the same cube.
7. **Standard interfaces at the edges.** Plain Postgres for serving. Standard
   MCP over Streamable HTTP with Entra auth for agents. A CSV and JSON export
   of the metric catalog that any glossary or catalog can import (Meta Hub,
   Purview, Snowflake Horizon).
8. **The cost model takes any cost source.** Azure exports come in now.
   Snowflake credits, Fivetran usage, Fabric capacity and Boomi licences come
   in as seeds or sources when a candidate is evaluated, because none of them
   is on the Azure bill.

### 9.4 What the contracts can't check

- **Where the work lives.** Low-code tools often keep pipelines inside their
  own platform. That weakens git history, code review and CI/CD, which are
  all on the best-practice list. Score it in the scorecard; no conformance
  test will catch it.
- **Connector coverage.** HubSpot is in most catalogs and X3 is reached
  through SQL Server, but Netstock is likely to be a custom build everywhere.
  dlt is strong at custom REST sources, which is worth weighing.

## 10. Phases

Each phase ends with the platform runnable end to end. Sizes are rough, for
one person working with Claude Code, and get refined after the Phase 0
spikes.

### Phase 0 · Foundation and spikes (about 1 week)

- **Housekeeping:**
  - tag `v1-prequel`
  - switch to `pyproject.toml` and uv, and add the Makefile, `config/`,
    `CLAUDE.md` and `.env.example`
  - move to the new folder layout
  - delete the cut list in §5
  - rename everything that carries the client's name (the dbt project, the
    profile, the home-directory environment variable, README and doc
    titles), and add the blocked-word check and pre-commit hook
    (§2, principle 6)
- **Spikes,** each a yes or no with a fallback:
  1. a set of `dbt-core`, `dbt-duckdb` and `dbt-metricflow` versions that
     work together, with `mf query` and the Python API on DuckDB, plus which
     YAML spec version to use
  2. dbt-duckdb reading bronze from Azurite or ADLS
  3. dlt appending Delta tables to `az://`, and DuckDB reading them back. If
     either fails, bronze stays plain Parquet (D3).
  4. **The Power BI route** (resolved by D12, which takes what was the
     fallback): import MetricFlow's saved-query results at fixed grains, with
     only sum and divide measures in Power BI.
  5. the generated TMDL opening in Power BI Desktop and refreshing the cube
     from ADLS Parquet. This needs a Windows machine (Q-F).
  6. Splink on the customer domain, scored against ground truth
  7. **The T-SQL path.** MetricFlow renders the three test metrics as
     Postgres-style SQL, sqlglot translates them, and they run on a SQL
     Server container holding a copy of v1's gold. Compare the results with
     DuckDB and record which constructs break. If it mostly fails, the T-SQL
     path drops to a known limit, and the other ways out in §9.1 stand.
- **A minimal Dagster definitions file and CI** running lint, unit tests,
  `dbt build` on the existing static mock, and the SQL portability check
  (§9.3, rule 3). Starting the check before any new SQL is written is what
  keeps it cheap.
- **Exit:** `make mock && make run` builds gold for the three sources
  locally, CI is green on PRs, and every spike has a result.

### Phase 1 · Sources, incremental ingestion and CDC (about 1.5 weeks)

- **The generator:** three systems, ground truth, the new X3
  tables, the clock, and CDC change tables.
- **dlt pipelines from the C1 specs:** X3 through CDC, HubSpot through the
  cursor plus the archived pass, Netstock as a snapshot. They write the C2
  bronze changelog with frozen schemas.
- **The `bronze_current` macro** and the bronze models.
- **The ingestion conformance test,** including deletes and the
  retention-exceeded resnapshot.
- **Exit:** a day-0 backfill and N simulated incremental days read only the
  changed rows and converge exactly on the source state. That gets proven in
  CI.

### Phase 2 · MDM, silver and gold (about 1.5 weeks)

- **MDM:** the C3 contract, the Splink provider, and the rules provider
  ported from v1.
- **Silver:** staging and conformed entities.
- **Gold:** the star from §7.5, with enforced contracts, owners, tests, and
  the GL reconciliation.
- **Exit:** gold contracts are enforced, and swap drill 1 passes MDM
  conformance with nothing downstream changed.

### Phase 3 · Semantic layer and golden answers (about 1 week)

- **MetricFlow:** semantic models, the time spine with fiscal granularity,
  and the metrics from §7.5.
- **Governance:** `meta`, the lint, the backlog, and the
  process/department/matrix seeds.
- **Serving:** saved queries and the materializer, the catalog generator, and
  `semantic_service.py`.
- **Golden answers**, and the Ossie export in CI.
- **The T-SQL backend for `semantic_service`**, with its CI test.
- **Stretch:** swap drill 4, the Boring Semantic Layer.
- **Exit:**
  - Any valid metric, dimension and grain combination answers.
  - Invalid ones are refused with a reason.
  - The marts materialize.
  - The golden answers pass in CI.

### Phase 4 · Downstream routes (about 1.5 weeks)

- **Power BI:**
  - the cube materializer and `dashboard_cube`
  - the model generator with the three measure templates
  - the process, department and account pages, which you build in Desktop
  - the parity queries, local and remote
- **The data service:** FastAPI with REST and MCP, `.mcp.json`, `AGENTS.md`,
  and the Claude Code skill.
- **The dlt reverse load to Postgres** and the `/datasets` endpoints.
- **The embedded AI example app.**
- **Exit:** one metric shows the same value in Power BI, in a mart, in an MCP
  answer and from the API, checked by the golden answers and parity tests.

### Phase 5 · Azure, CI/CD and operations (about 1.5 weeks)

- **Infrastructure and deployment:**
  - Bicep for dev, with test and prod parameterised
  - the container image and CD workflows
  - Power BI workspace deployment
  - automated `executeQueries` parity in test
- **Operations:**
  - alerts and Log Analytics rules
  - the `ops` schema and the Platform Health page
  - the cost export ingest and the Platform Cost page
- **Exit:**
  - A merge deploys to dev and runs nightly.
  - Promotion to test works through an approval.
  - A deliberately broken run raises an alert.
  - Cost by component is visible.

### Phase 6 · Governance, documentation and the evaluation package (about 1 week)

- **Governance:** the hosted catalog, exposures, the ownership and PII
  checks.
- **Documentation:** `docs/components/*.md` (contract, baseline, how to swap,
  candidates), a rewritten architecture doc and diagrams, the pruned and
  extended open questions.
- **The evaluation registry, the scorecard and a client demo script.**
- **Exit:** a client-ready walkthrough, and an evaluation kit ready to score
  candidate stacks.

## 11. Definition of done for the POC

1. One command builds the whole platform locally from synthetic sources, and
   it runs nightly in Azure dev.
2. N simulated days load only what changed, deletes included, and bronze
   converges exactly on the source, with a test proving it.
3. Every metric gives the same value through Power BI, the marts, MCP and the
   API, and golden answers plus parity tests check it.
4. Any valid metric × dimension × grain is answerable. An invalid one is
   refused with a reason, and a blocked or placeholder metric returns no
   number.
5. The MDM provider swaps between Splink and the rules matcher by config, with
   no change downstream, and both have a published match-quality score.
6. PR → CI (end to end on mocks) → dev → approval → test → prod works.
7. A deliberately induced failure raises an alert, and cost is visible by
   component and environment.
8. Owners, the catalog and lineage are visible from a source table to a
   dashboard tile.
9. The evaluation kit is in place: the component registry, conformance
   suite, golden answers, scorecard and cost capture.
10. The evidence for the swap promise is green in CI: silver and gold pass
    the portability check, the pipeline runs without Dagster, the Ossie
    export runs, and the golden answers pass through the T-SQL path.
11. The client's name appears nowhere in the repo, and the blocked-word
    check is green.

## 12. Decisions this plan makes, and open questions

### Decided here (say so if you disagree)

| # | Decision | Why |
|---|---|---|
| D1 | MetricFlow YAML replaces the custom metric YAML and compiler. Governance fields go in `meta`, and unfinished metrics go in `backlog.yml`. | It is the baseline in the stack menu, it is Apache 2.0 since Oct 2025, and it does "any valid combination and grain" natively. v1's objection, that a time dimension is required, is handled by giving every semantic model one. |
| D2 | On-time delivery moves from Pangea to X3 deliveries. Freight cost metrics go to the backlog as blocked. | Pangea is out of scope, and X3 holds the delivery documents. |
| D3 | Bronze is an append-only changelog stored as Delta tables, with plain Parquet as the fallback if the Phase 0 spike fails. | Two of the three other stack columns sit on Microsoft, and a Fabric Lakehouse reads Delta folders as tables through a OneLake shortcut, with no copy. DuckDB reads Delta too. |
| D4 | The warehouse is rebuilt fully from bronze each run. Incremental happens at ingestion. | It meets the requirement, and it is simpler and deterministic. One incremental dbt model shows the pattern for scale. |
| D5 | One data service runs REST and MCP together, and Postgres serves both Dagster and the app tables. | Fewer moving parts. |
| D6 | The mock database is generated at setup, not committed. | It takes 1.3 seconds and avoids 17 MB diffs in history. |
| D7 | Department impact is attributed through the person who performed the activity: X3 user or HubSpot owner → employee → department. | It is the only attribution the sources support without inventing one. |
| D8 | GitHub Actions and Bicep. | Both are native and lean; Azure DevOps or Terraform can stand in. |
| D9 | No Boomi, or any other commercial component, is built into the POC. MDM uses open-source providers behind C3. | The client is leaning towards Boomi, not committed. The POC is the open-source baseline that commercial options get compared against. |
| D10 | MetricFlow stays usable on a T-SQL warehouse through a sqlglot translation step, tested in CI against a SQL Server container. No second stack is built now. | It keeps MetricFlow in play if Azure SQL MI or Fabric wins the warehouse evaluation, for a few hundred lines and one CI job. A full build on the client's existing stack comes later, once this baseline is settled. |
| D11 | No client name anywhere in the repo, enforced by a check whose word list lives outside git. | A clean repo can be shown to anyone, and the baseline can serve other clients later. |
| D12 | Power BI imports one table, `dashboard_cube`, holding every saved query's results stacked, ratio components included. Each KPI is one generated measure from three guarded templates (`SUM`, `DIVIDE(SUM, SUM)`, a single-row value). No DAX is translated from the semantic layer. | MetricFlow computes every dashboard number, so dashboards match the other routes by construction rather than by a parity test of two engines. The guards make a wrong number impossible; a report mistake shows a blank. It is the more common pattern, any BI tool can read the same table, and the cube is small (about 5,000 rows here). The cost: dashboards slice only along the grains the saved queries name, and a new grain is a reviewed YAML change. Ad hoc questions go to chat and the API, which query MetricFlow at any grain. |

### Open questions for you or the client (none of them block Phase 0)

| # | Question | Affects |
|---|---|---|
| Q-A | What are the departments, and what does "departmental activity" mean to the business? Is D7's attribution through the person right? | §7.5 seeds and `dim_employee` |
| Q-B | Which processes and departments own which placeholder metrics? The process acronyms are still unexpanded. | Seeds only |
| Q-C | Where does X3 run (on-premises, partner-hosted, Sage cloud), and which SQL Server edition? Can CDC or Change Tracking be enabled? | The X3 CDC path, network design |
| Q-D | What Power BI licensing does the client have (Pro, PPU, Fabric capacity)? | Deployment pipelines, the XMLA and API deployment route, Direct Lake |
| Q-E | Which master data domains will the chosen MDM have to cover (customer, item, supplier, employee), and does it need to sync back into X3 and HubSpot? | The scope of C3, the MDM evaluation criteria |
| Q-F | Is there a Windows machine for Power BI Desktop (a VM, or a Dev Box)? | Phase 0 spike 5, the Phase 4 reports |
| Q-G | Which Azure subscription, region and naming convention, and who approves spend? | Phase 5 |
| Q-H | Is GitHub or Azure DevOps the client's standard? | §7.9 |
| Q-I | What should the project be called (default `control_tower`)? The repo folder and remote are yours to rename. Will the repo ever be shared beyond the client? Earlier commits on this branch name the client, so sharing means starting a fresh repo from the cleaned tree rather than pushing this history. | Phase 0 housekeeping |
| Q-J | Do details that came from the client but don't name them, such as the process acronyms and the site cities in the mock data, also need to go? | Seeds, the mock generator |

The v1 open questions that still apply (DSO basis, fiscal calendar,
survivorship, ownership, currency, match and count tolerances, Return Rate
basis and date) carry over into `docs/open_questions.md`. The Pangea and
Paycom questions are dropped. Question 11 (as-was history) is reframed,
because the CDC changelog keeps the history (§5).

## 13. Risks

| Risk | Mitigation |
|---|---|
| The warehouse and semantic layer choices are coupled: MetricFlow doesn't support Azure SQL or Fabric | Say so up front (§9.1). The T-SQL path is the first answer, and it is tested in CI. Consumers depend on C6 only, the Ossie export shows what would translate, and drill 4 keeps the Boring Semantic Layer, whose Ibis base supports SQL Server, in the evaluation. |
| sqlglot can't translate some of MetricFlow's SQL into T-SQL (percentiles and date functions are the likely gaps) | Phase 0 spike 7 finds the gaps early. The CI test names any metric that fails, and that metric becomes a known limit for a T-SQL warehouse instead of a silent wrong number. |
| The SQL Server container runs under emulation on Apple Silicon | CI runs it natively on Linux. Locally it is optional. |
| New SQL quietly picks up DuckDB-only syntax and makes later swaps into rewrites | The sqlglot portability check in CI from Phase 0. |
| The pinned `dbt-core` 1.12 may not have a matching `dbt-metricflow` release, or the YAML spec may be changing | Phase 0 spike 1. Pin the trio together. |
| A dashboard needs a fixed metric (a distinct count) sliced freely, and the cubes multiply | Give it one cube per grain the page shows; the guard blanks anything else. If that grows combinatorially, that one metric gets a narrow detail table in the model, an exception D12 allows. |
| Mock CDC behaves differently from real SQL Server CDC (LSN types, retention, the capture job) | The optional SQL Server compose profile. A resnapshot path tested with the clock. |
| No Power BI runtime on a Mac | A Windows VM or Dev Box (Q-F). `executeQueries` parity runs in the test workspace. |
| The X3 table names (`SDELIVERY`, `AUTILIS`, `STOCOUNT`) differ in the client's folder | Mark them unverified, as v1 does. Staging absorbs renames. |
| Scope creep from five downstream routes | Each route is a thin reference implementation over the same service. Depth goes to the matrix dashboards and the semantic layer. |
| A DuckDB file is single-writer | Dagster is the only writer. Consumers read the published read-only copy. |
