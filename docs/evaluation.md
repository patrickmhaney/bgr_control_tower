# The evaluation kit

This baseline is the reference implementation the software evaluation is
measured against. The kit turns "could tool X replace this component?" into
tests and numbers.

| Piece | Where | What it answers |
|---|---|---|
| Component registry | `evaluation/components.yml` | For each component: requirements served, contract, baseline, how to swap, candidates from every stack column, swap cost |
| Conformance tests | `tests/conformance/` | Does a replacement produce the contract? Ingestion convergence (C2), MDM contract and match quality (C3), gold contracts (C4, in dbt), golden answers (C5), API and MCP (C6), governance and portability |
| Golden answers | `projects/<slug>/golden_answers.yml` | Does a semantic engine or BI tool give the same numbers? 32 queries with frozen answers, 5 that must be refused |
| Scorecard | `evaluation/scorecard.md` | How does a candidate score on requirements, best practices, cost, portability, maturity? |
| Cost capture | `gold.fct_cloud_cost`, `seeds/license_cost.csv` | What does each component cost to run, plus licences? |
| Swap drills | below | Do the modularity claims hold? |

## Golden answers

Each query names metrics and dimensions the way the semantic layer does, an
independent `reference_sql` written by hand against gold, and the frozen
answer. `python -m evaluation.golden check` requires the semantic layer, the
reference SQL and the frozen answer to agree; `--backend tsql` runs the same
check through the T-SQL path. The answers hold for the sources as of
2026-09-05 after `make mock run`. Queries that depend on which MDM provider ran
are marked `mdm_sensitive` and keep one answer per provider.

To test a candidate - Cube, a Power BI or Fabric semantic model, Snowflake
semantic views - load the same gold into it, define the same metrics, and
reproduce `expected`. For Power BI, `projects/<slug>/powerbi/parity/parity_queries.json` is
the subset the cubes can serve, as DAX; `python -m serving.powerbi_parity local`
proves the cube and measure templates reproduce it without Power BI.

## Swap drills

| Drill | Status | How |
|---|---|---|
| 1. MDM provider: Splink ↔ rules | done | `python -m ctl build --provider rules`. Nothing downstream changes; match quality is reported |
| 2. Warehouse engine: DuckDB → Postgres | stretch | dbt-postgres for silver and gold (they port), a bronze adapter, MetricFlow's Postgres renderer |
| 3. BI consumer: the cube through Power BI | local in CI; remote ready | `python -m serving.powerbi_parity local` (templates' SQL twin), `run` against a deployed model |
| 4. Semantic engine: MetricFlow ↔ Boring Semantic Layer | stretch | define the same metrics over gold, run the golden answers, compare its MCP server |
| T-SQL path | in CI | gold loaded into SQL Server 2022, golden answers through `--backend tsql` |

## What the tests cannot check

Score these in the scorecard: whether a low-code tool keeps its work in git
(history, review, CI/CD), connector coverage (Netstock is a custom build almost
everywhere), the operating model a lean team can sustain, and licence terms.
