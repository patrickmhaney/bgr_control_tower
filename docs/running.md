# Running it

## Setup

Python 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
make setup        # uv sync --all-extras, then dbt deps
make mock         # the synthetic sources as of 2026-09-05
make run          # ingest, build, MDM, cubes, serving load (~1 minute)
make golden       # 37 golden answers: semantic layer == reference SQL == frozen
make test         # unit and conformance tests
```

Everything the pipeline writes lives under `.data/<project>/` (gitignored).
`make reset` deletes it.

## Projects

Every command works on one project pack under `projects/` (see
[architecture.md](architecture.md#architecture-and-projects)). The default is
`sample_v2`, so the commands above need no flag. For another pack:

```bash
make setup mock run golden PROJECT=sample      # or: export CT_PROJECT=sample
python -m ctl --project sample run             # the step commands take --project
python -m ctl check-pack sample                # the pack fills the fixed slots only
python -m apps.studio --port 8801 --project sample   # switchable in the Studio header
```

Each pack has its own data directory (`.data/<slug>/`) and dbt target
(`projects/<slug>/target/`), so packs run side by side and never share a
manifest or a row.

## The step commands

Every step runs on its own, which is what Dagster calls and what any other
orchestrator could call:

| Command | Does |
|---|---|
| `python -m ctl sources init` | Rebuild the mock sources as of the initial date |
| `python -m ctl sources advance --days N` | Move the sources forward N days (new orders, payments, deliveries, deletes) |
| `python -m ctl ingest [--source S] [--full-refresh] [--reconcile]` | Extract into the bronze changelog |
| `python -m ctl dbt <args>` | dbt with the environment's locations set |
| `python -m ctl mdm [--provider splink\|rules]` | Run MDM and land contract C3 |
| `python -m ctl build [--stage raw\|clean\|mdm\|model]` | dbt before MDM (bronze, then staging and seeds), MDM, dbt after MDM - or one stage |
| `python -m ctl materialize` | Saved queries → cubes, stacked into `dashboard_cube` for Power BI |
| `python -m ctl serve-load` | Marts → the serving database |
| `python -m ctl publish` | Copy the warehouse file to raw storage |
| `python -m ctl run` | The daily pipeline |
| `python -m ctl powerbi` | Regenerate the Power BI model and parity queries (files in git; only when the semantic layer changes) |
| `python -m ctl check-pack [slug]` | The pack fills the fixed slots only: no Python, the template `dbt_project.yml`, known keys, one bronze model per spec table |
| `python -m ctl new-project SLUG [--name NAME]` | A project in requirements only, from the platform template: no source systems yet, empty seeds and semantic files, an empty `requirements/` (the Studio's New project does the same and commits it) |
| `python -m ctl kpis` | Each KPI's latest full month and the month before, as JSON (a sanity check after a build) |

## The Studio

```bash
make studio                               # http://localhost:8800
```

A small web app for showing the platform to people who don't read code
(`apps/studio/`). **Architecture** draws the components and the contracts
between them, and switches between the stack options to show what each would
put in each box - and that the contracts don't move. **Run the pipeline**
steps through a day one stage at a time. Every button runs the real step
commands, then the boundary check for that stage (C2 to C7) - the same
functions the conformance tests call - and shows what happened in plain
numbers. The customer matcher toggle swaps the MDM component (Splink or rules)
and re-runs from the match. Clicking a contract opens its definition files and
its tests (`apps/studio/content.yml` lists both); **Run tests** runs them and
shows each case as it passes. A full day takes about 30 seconds; reset rebuilds
day 0 in about the same.

Three **preview** screens read what the pipeline produced, each through a
route that already exists, so they complete the flow end to end without being
the delivered product:

| Screen | Reads | Through |
|---|---|---|
| **Governance** | every metric with its definition, accountable owner, department responsibility, measures and their data owners, lifecycle stage, golden answers and source lines | the semantic layer's catalog (`semantic/catalog.py`), the compiled manifests, `semantic.lint`, the golden answers and the data service's audit log |
| **Dashboards** | one report page per saved query: period and as-of pickers, slicers, KPI cards against the prior period and prior year, a trend with last year's line, breakdown bars that cross-filter, a member-by-month heatmap, a sortable scorecard table with CSV export, and each metric's definition and Power BI measure | `marts.dashboard_cube` and the Power BI measure templates' SQL (C7) - the numbers the Power BI model shows |
| **Query → Metrics** | any metrics by any valid dimensions, with the SQL MetricFlow wrote | the semantic service (C5, C6); invalid cuts are refused with the reason |
| **Query → SQL** | gold and the marts, read-only: one statement, 1,000 rows, 15 seconds, no file access | DuckDB |
| **Ask** | questions in plain English, each tool call shown | `apps/examples/ask_metrics` - Claude with the four governed MCP tools (C6); needs `ANTHROPIC_API_KEY`, and sends questions and results to the Claude API |

The frozen golden answers hold only for day 0, so on later days the Studio
checks that the semantic layer and the hand-written reference SQL agree
(`python -m evaluation.golden check --live`, `python -m serving.powerbi_parity
local --live`). It listens on localhost only, because it runs commands; on a
VM it belongs behind Entra ID sign-in.

## One run at a time

The warehouse is one DuckDB file and dbt has one target folder, so two runs at
once collide. Every step command that writes takes `.data/<project>/pipeline.lock` for
as long as it runs (`core/lock.py`); a second one stops at once and names the
first. The Studio checks the lock too: while a run started elsewhere holds it,
its buttons wait and its screens say why. A lock left by a process that died is
taken over. Dagster calls the step functions directly, not the commands, and
relies on its run queue (one run at a time) instead.

## Watch incremental refresh work

```bash
make mock run
make advance DAYS=3
python -m ctl ingest --source sage_x3     # reads a few hundred CDC rows, not 100,000
python -m ctl sources status              # LSN counters and change rows retained
make advance DAYS=6                       # longer than CDC retention (3 days)
python -m ctl ingest --source sage_x3     # takes a fresh snapshot instead of leaving a hole
```

`tests/conformance/test_ingestion_convergence.py` does this end to end in a
temporary directory and checks bronze equals every source table afterwards.

## Ask the semantic layer

```bash
make serve                                # http://localhost:8000/docs
curl -s localhost:8000/query -H 'content-type: application/json' \
  -d '{"metrics": ["on_time_delivery_rate"], "group_by": ["site__site_name"]}'
```

Or from Python:

```python
from serving.semantic_service import SemanticService
svc = SemanticService()
svc.query(["return_rate"], group_by=["employee__department_name", "metric_time__quarter"])
```

Or with MetricFlow directly, from `projects/<slug>/` with the environment set:
`python -m ctl dbt parse` first, then `mf query --metrics win_rate --group-by employee__department_name`.

**Claude Code** picks up the MCP server from `.mcp.json` - ask "which site has
the worst on-time delivery this year?" in this repo.

**The embedded-AI example** needs Anthropic credentials (`ANTHROPIC_API_KEY`
or `ant auth login`):
`uv run python -m apps.examples.ask_metrics.app "How is win rate by department?"`

## Dagster

```bash
make ui                                   # http://localhost:3000
```

Jobs: `daily` (everything, schedule 06:00), `weekly_reconcile` (HubSpot hard
deletes, Sundays), `cdc_resnapshot` (manual). Set `CT_ALERT_WEBHOOK` to a Teams
or Slack incoming webhook to get failed runs posted.

## Swap drill 1: the MDM provider

```bash
python -m ctl build --provider rules
```

Nothing downstream changes - silver reads only contract C3. The match quality
changes, and `.data/<project>/mdm_quality.json` says by how much. The golden answers
that depend on matching are marked `mdm_sensitive` and keep one answer per
provider.

## Environments

`PLATFORM_ENV` selects `config/<env>.yaml` (`local`, `dev`, `test`, `prod`). Any
key can be overridden with `CT_<KEY>`. In Azure, the image runs as two
container apps from `infra/main.bicep`; see [components.md](components.md) for
what each resource is.

## When something breaks

| Symptom | Likely cause |
|---|---|
| `No semantic manifest` | run `python -m ctl dbt parse` |
| A new column fails ingestion | the source changed under contract C2 - review, then `python -m ingestion.run --freeze-schemas` and commit the schema diff |
| A golden answer fails | a number changed. If intended, `python -m evaluation.golden freeze` and explain the diff in the PR |
| Seed load error after a seed's columns change | the old table is still in the warehouse: `python -m ctl dbt seed --full-refresh` |
| MCP returns `Invalid Host header` | set `CT_ALLOWED_HOSTS` to the service's host name |
