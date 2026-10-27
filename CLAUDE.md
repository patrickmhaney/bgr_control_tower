# Working in this repo

An open-source baseline data platform. [PLAN.md](PLAN.md) holds the design
and decisions; [docs/architecture.md](docs/architecture.md) is the as-built
overview. Read them before changing structure.

The repo is one **architecture** plus **project packs** under `projects/<slug>/`
(default `sample_v2`; pick another with `ctl --project`, `CT_PROJECT` or
`make ... PROJECT=`). A pack holds content only: metrics, seeds, golden
answers, `scenario.yml`, specs and SQL. `core/project.py` builds every
content path.

## Rules

- **Never name the client.** Not in code, config, docs, data, branch names or
  commit messages. Write "the client". `python -m checks.blocked_words` and
  the pre-commit hook enforce it; the word list lives outside git.
- **Packs hold no Python and fill fixed slots** (`python -m ctl check-pack`).
  New mechanics - a source system, a macro, a staging adapter - go in the
  architecture (`sources/simulators/`, `transform/platform/`), available to
  every project. A pack's `dbt_project.yml` is the platform template; only
  `name` and `vars` differ.
- **Measures live only in a pack's `models/semantic/`.** Never write measure
  logic in SQL views, Power BI or app code. Arithmetic goes in the gold fact;
  measures are aggregations over bare columns (`python -m semantic.lint`).
  Power BI imports `marts.dashboard_cube` and its measures are generated from
  three guarded templates (`SUM`, `DIVIDE(SUM, SUM)`, single-row value) -
  never hand-write DAX. A dashboard grain is a saved query.
- **Silver and gold SQL must port** to T-SQL and Snowflake: dbt cross-database
  macros, no `QUALIFY`/`EXCLUDE`/`GROUP BY ALL`/`::`/positional `GROUP BY`/
  `USING`. Flags are 0/1 integers. `python -m checks.portability`.
- **Contracts are files.** Changing C1-C7 (see docs/architecture.md) is a
  reviewed change; never re-freeze a pack's `ingestion/schemas/` to silence a failure.
- **Orchestration stays thin.** New steps go in `ctl/__main__.py` (and the
  module they call); Dagster assets only call them.
- **Generated files** (a pack's `powerbi/` and `docs/metric_catalog.md`) are regenerated,
  never edited: `python -m ctl powerbi`, `python -m semantic.catalog`.
- **A changed number is a changed golden answer.** Re-freeze with
  `python -m evaluation.golden freeze` and explain the diff.

## Commands

`make setup mock run golden test lint` (add `PROJECT=<slug>` for another pack).
Every step: `python -m ctl --help`.
The metrics are queryable through the `control-tower` MCP server (`.mcp.json`).

## Skills

`.claude/skills/`: build-from-requirements, add-metric, add-source-table, swap-component, run-the-platform.
