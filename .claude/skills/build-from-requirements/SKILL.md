---
name: build-from-requirements
description: Build a project's measures from its requirements - read requirements/ and backlog.yml, write the build logic (source systems, sample-data settings, SQL, measure formulas, saved queries, proposed golden answers), move each built measure from backlog.yml to metrics.yml, and pass every gate. Use when asked to "build the measures that are ready", build a project, or turn requirements into numbers.
---

The business's side of a project is already in its files: `projects/<slug>/requirements/` (processes, dimensions, the bus matrix, dashboards, each measure's answers, sketches) and the definitions in `backlog.yml` and `models/semantic/metrics.yml`. Nothing is handed over; this skill writes the **build logic** next to it. Ask which project if it isn't obvious (`ls projects/`; a project with `systems: []` has never been built) and run every command on it (`CT_PROJECT=<slug>`).

## 1. Read, then say what is ready

Read `requirements/*.yml`, `backlog.yml`, `project.yml` (`business_systems` maps the business's system names to architecture systems, `null` = none yet), `docs/open_questions.md` and `sources/systems.yml`. For each measure in `backlog.yml`, decide whether it is ready:

- **ready**: question 3 (the calculation) is answered; every source system it names maps to an architecture system with a simulator; its status is `placeholder`, not `blocked`; its `unblock_requires` are met.
- **waiting**: say for what - an answer, a source system to connect, a decision, data no system has. Don't guess an answer the business left as "I don't know"; it is in `docs/open_questions.md` with who might know.

List both to the user before building, and build only what they agree is ready.

## 2. A project's first build (`systems: []`)

1. Set `project.yml` `systems` to the architecture systems the ready measures need, and map each business system in `business_systems` (a system with no simulator stays `null`: its measures wait).
2. Write `scenario.yml`: start from a sample project's, keep every key `python -m ctl check-pack` requires, and fit volumes, companies and sites to the process answers (volume, sites, systems). Synthetic and fictional only: no real names.
3. For each system, the extraction spec, bronze models and staging through the **add-source-table** skill. Freeze schemas once, on the first run (`python -m ingestion.run --freeze-schemas`), and never again to silence a failure.
4. Gold: the dimensions the bus matrix ticks (each `requirements/dimensions.yml` code becomes an entity, so `customer` is `customer__...`; `date` is `metric_time`), and one fact per process at the grain its "What it records" answer gives.

## 3. Each ready measure

Follow the **add-metric** skill (cases A-D) with these rules:

- **The definition belongs to the business.** Move the entry from `backlog.yml` to `models/semantic/metrics.yml` keeping its `name`, `label`, `description`, `owner`, `owner_proposed` and `caveats` exactly as written (they go under `config.meta`, except label and description). The name never changes: golden answers and Power BI refer to it. Remove it from `backlog.yml` in the same change; a metric exists once.
- Formula from the answers: question 3 (calculation), 4 (sources), 7 (breakdowns), 8 (date and periods). Arithmetic goes in the gold fact; the measure is an aggregation over a bare column. Silver and gold SQL must port (no `QUALIFY`, `::`, `USING`, positional `GROUP BY`; flags are 0/1).
- Status `provisional`, with a `provisional_reason` saying what isn't proven yet (usually: not yet tested against the trusted report named in question 6). `active` only when the user says the number has been checked. Add `requirement: <dashboard code>-<slot>` from `seeds/process_metric.csv`.
- Saved queries: the KPI goes in `mart_company_monthly` and in its process dashboard's cube (`mart_<code>`). The cube's grain carries every dimension the dashboard's sketch filters or breaks down by and the bus matrix ticks for that process, so the Dashboards page "As sketched" shows no tile it can't honour.
- `seeds/process_metric.csv`, `department_metric.csv`, `department.csv` and `process.csv` are the Requirements tab's: don't edit them.

## 4. Golden answers

For each built measure, propose at least a total and one breakdown the sketch uses, each with an independent `reference_sql` against gold. Freeze (`python -m evaluation.golden freeze`) and show the user every new number and every changed one, with why. A changed number is a changed golden answer.

## 5. The gates, all of them

```
python -m ctl check-pack && python -m ctl requirements
make lint                                  # ruff, check-pack, governance lint, portability
make mock run golden test                  # fresh sources, the pipeline, golden answers, tests
python -m semantic.catalog && python -m ctl powerbi    # generated files, never edited by hand
python -m ctl kpis                         # each KPI's latest month: a sanity check to show the user
```

Then open the Studio (`make studio`) on the project: Requirements, Bus matrix shows no "!" on a tick for a built measure; Dashboards shows each sketched page with no tile issue; Governance shows the measure with its owner and caveats.

Report what was built, its numbers, what still waits and for what. Don't commit unless asked; say that the Studio saves only over committed files, so the build should be committed before anyone edits the requirements again. Never name the client. A project holds no Python: new mechanics go in the architecture.
