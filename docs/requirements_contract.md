# The requirements contract (C8)

The requirements tool (the product) captures what a project's measures mean:
definitions, owners, dashboards, breakdowns. This platform (the target) holds
how they are computed. **C8 is the one thing the product knows about the
target**: a JSON export, the *requirements spec*, checked against
[`semantic/requirements_spec.schema.json`](../semantic/requirements_spec.schema.json).

A compiler on the product side turns a spec into the pack's "what" files -
files this repo already understands. The target has no importer code, and a
compiled change lands as an ordinary reviewed diff, gated by the governance
lint and the golden answers.

Status: **in use, on the product side** (2026-10-25). The product exports the
spec (`GET /w/{slug}/requirements_spec.json`, validated against the schema),
its compiler (`python -m app.compiler`) writes a pack's "what" files, and its
reverse import (`python -m app.target_import`) built the Sample Project v2
workspace from this repo at `269ad97`. Compiling that workspace reproduces
`projects/sample_v2/` exactly. This repo still reads nothing but the files.

## Rules

- **People are roles.** An owner, a subject-matter expert or a process step
  names a job title or team (`VP Operations`), never a person or an email.
  There is no field for either, and every object rejects unknown keys.
- **No client name**, in the spec or in anything compiled from it. The
  compiled files pass `python -m checks.blocked_words` like any other change.
- **One project per spec.** Two projects that both have a "$ Sales" share
  nothing. Within a spec a measure is defined once, by `name`, and dashboards
  refer to it.
- **"I don't know" is an answer**: `{"unknown": true, "who_might_know": "<role>"}`.
  A single-box answer ("No known problems", "No trusted report") is
  `{"none": true}`. A blank answer is left out.
- **What, not how.** The spec carries what the business said. A few fields are
  *bindings* - engineer-set links from a business term to the semantic layer
  (a dimension's `code`, a cube's `group_by`, a measure's `format` and
  `direction`). Gold and silver SQL, `semantic_models.yml`, component
  metrics, extraction specs and `scenario.yml` are never in the spec: the
  free-text calculation cannot regenerate SQL.
- **Versioned.** `spec_version` is `1`. A breaking change bumps it and is a
  reviewed change in this repo, like C1-C7.

## What it compiles to

| Spec | Target file |
|---|---|
| `measures[]` without `backlog` | a KPI in `projects/<slug>/models/semantic/metrics.yml` (`role: kpi`) |
| `measures[]` with `backlog` | an entry in `projects/<slug>/backlog.yml` |
| `cubes[]` | `projects/<slug>/models/semantic/saved_queries.yml` |
| `dashboards[].slots` | `projects/<slug>/seeds/process_metric.csv` |
| `department_metrics[]` | `projects/<slug>/seeds/department_metric.csv` |
| `departments[]` | `projects/<slug>/seeds/department.csv` |
| `processes[]` | `projects/<slug>/seeds/process.csv`; steps, systems and volume feed docs and the scenario |
| `project` | `project.yml` (from Phase 1b: `projects/<slug>/project.yml`) |
| `dimensions[]`, `bus_matrix[]` | nothing written; checked against the semantic models' entities |
| `dashboards[].tiles` | the Studio's dashboard pages |

Paths are today's. Phase 1b moves them into `projects/<slug>/`; the mapping
does not change.

## Field by field

### Measures

| Product | Spec | Target |
|---|---|---|
| Measure name | `label` | `label` |
| (none yet) | `name` | metric `name`. The product must store it once set, so a renamed label never renames the metric |
| Definition | `definition` | `description` |
| Calculation | `calculation.text`, `.numerator`, `.denominator` | a ratio's numerator and denominator, by label; otherwise a draft for review |
| Source systems | `sources` | none; a source not in scope means `backlog.status: blocked` |
| Benchmark or target | `target` | none yet. A home (`meta.target`) is an open decision |
| Trusted report | `trusted_report` | a golden answer's `expected`; its reference SQL is written by hand |
| Breakdowns | `breakdowns` (dimension codes) | the cubes the measure appears in; each must be a valid group-by |
| Date and periods | `time_basis` | docs and `caveats` |
| Refresh | `refresh.cadence`, `.why` | the schedule |
| Changes to past numbers | `restatement` | docs and `caveats` |
| Definition owner | `owner` | `owner: <role>`; unknown is `owner: TBD`, `owner_proposed: <who_might_know>` |
| Subject matter expert | `sme` | none |
| Status: complete | `status: complete` | `status: active` |
| Status: in progress, or flagged | `status: in_progress`, or `followup.note` | `status: provisional`, `provisional_reason` from the follow-up note |
| Status: not started | `status: not_started` | not compiled, unless `backlog` is set |
| Notes, known issues | `caveats` (one per line), `notes` | `caveats` |
| (none: engineer-set) | `format`, `direction` | `format`, `direction` |
| (none: engineer-set) | `backlog.status`, `.reason`, `.unblock_requires` | `status: placeholder` / `blocked`, `placeholder_reason` / `blocked_reason`, `unblock_requires` |

Each compiled metric on a process dashboard gets
`meta.requirement: <process>-<slot>` (e.g. `O2C-M1`), so a number traces back
to the conversation that defined it. The
defining slot is the first one that shows the measure, in process
`display_order` then slot order - in the product, the row where it is defined
rather than shown "also on". The governance lint allows the key and checks
its shape.

### Dashboards and departments

| Product | Spec | Target |
|---|---|---|
| Dashboard row (code = a process code) + measure slot | `dashboards[].process`, `.slots[]` | `process_metric.csv`: `process_code`, `metric_name`, `slot`, `display_order`. Slots M1-M12 match |
| A measure shown on another row ("also on") | `department_metrics[]` | `department_metric.csv`: `department_code`, `process_code`, `metric_name`, `influence` |
| Departments | `departments[]` | `department.csv` |
| Who uses it, decisions, cadence, access | `audience`, `decisions`, `cadence`, `access` | docs; `access` drives row-level security later |
| Sketch tiles: headline, trend, comparison, table, filter, note | `tiles[].kind`: `kpi`, `line`, `bar`, `table`, `filter`, `text` | the Studio page: cards, trend, breakdown bars, scorecard table, slicers. The grain they need is a cube |

Which departments own or contribute to a measure, per process, is a target
binding the product stores beside the measure (its Ownership tab lists them);
there is no business question for it yet.

A measure that no process dashboard shows (it may still be in a cube) sits on
a dashboard row whose code is not a process code; such rows are not exported
as `dashboards`, and those measures get no `requirement` key.

### Processes, dimensions and the bus matrix

| Product | Spec | Target |
|---|---|---|
| Process, display order, active | `processes[].code`, `.display_order`, `.active` | `process.csv` |
| Purpose, start and end, what it records, decisions, pain points, priority | the same keys | docs |
| Steps (department, role, system) | `steps[]` | docs; the scenario's process shape |
| Systems | `systems` | `project.yml` systems; each must have a simulator and a staging adapter in the architecture |
| Volume | `volume` | `scenario.yml` volumes (drafted, then reviewed) |
| Dimension | `dimensions[].code` (binding) | a semantic-model entity (`customer`, `site`, `item`, ...) |
| Identifier, attributes, roll-ups | `identifier`, `attributes`, `hierarchy` | gold `dim_*` columns and contracts (C4) |
| Master system | `systems` | MDM configuration (C3) |
| When it changes | `history.choice`: `as_was`, `as_is`, `both` | type-2 handling in the gold dimension |
| Known data problems | `quality` | `projects/<slug>/docs/sources.md` |
| Bus matrix tick | `bus_matrix[]` | a fact that joins the dimension through its entities |

The bus matrix and the semantic layer check the same rule from both sides: a
cell the product shows as a dashed suggestion is exactly a group-by the
semantic layer refuses ("cannot be grouped by"). The compiler fails on a tick
the semantic models cannot honour, rather than writing it.

### Cubes

`cubes[]` is `saved_queries.yml`, one to one: `name`, `description`,
`measures` (the saved query's `metrics`) and `group_by`, in MetricFlow
syntax. Cubes are listed, not derived from dashboard slots, because a cube
can carry a measure that is on no dashboard (`mart_o2c` carries
`unsettled_invoice_rate`) and a dashboard can need two cubes (a fixed metric
both by site and company-wide).

## The reverse import (target to product)

Sample Project v2 is built by reading this repo at `269ad97` into the
product with the same mapping, run backwards (Phase 2):

- questions the target can't answer - targets, trusted reports,
  subject-matter experts, process steps, volumes - become "I don't know";
- `owner: TBD` with `owner_proposed: <role>` becomes "I don't know, who might
  know: `<role>`";
- component metrics are not measures in the product; they are implementation.

Compiling that workspace again must reproduce the "what" files exactly
(Phase 3's round-trip test).

## Example

One active KPI, one blocked measure, the dashboard row that shows them and a
cube. Abridged: a real spec lists every department, process and dimension it
refers to.

```json
{
  "spec_version": 1,
  "project": {"slug": "sample_v2", "name": "Sample Project v2", "systems": ["Sage X3", "HubSpot", "Netstock"]},
  "departments": [{"code": "WHSE", "name": "Warehouse", "display_order": 4}],
  "processes": [{"code": "O2C", "name": "Order to Cash", "display_order": 2, "active": true, "status": "in_progress"},
                {"code": "I2D", "name": "Inventory to Delivery", "display_order": 5, "active": true, "status": "in_progress",
                 "volume": {"unknown": true, "who_might_know": "Warehouse Manager"}}],
  "dimensions": [{"code": "site", "name": "Site", "status": "complete", "systems": {"systems": ["Sage X3", "Netstock"]},
                  "history": {"choice": "as_is"}, "quality": {"none": true}}],
  "bus_matrix": [{"process": "O2C", "dimension": "site"}, {"process": "I2D", "dimension": "site"}],
  "dashboards": [{"process": "O2C", "slots": [{"slot": "M1", "measure": "on_time_delivery_rate", "display_order": 1}]},
                 {"process": "I2D",
                  "slots": [{"slot": "M2", "measure": "on_time_delivery_rate", "display_order": 2},
                            {"slot": "M4", "measure": "cost_per_shipment", "display_order": 4}],
                  "tiles": [{"kind": "kpi", "x": 0, "y": 0, "w": 3, "h": 2, "measure": "on_time_delivery_rate"},
                            {"kind": "filter", "x": 3, "y": 0, "w": 3, "h": 1, "dimension": "site"}]}],
  "department_metrics": [{"department": "WHSE", "process": "I2D", "measure": "on_time_delivery_rate", "influence": "owns"}],
  "measures": [
    {"name": "on_time_delivery_rate", "label": "On-Time Delivery", "status": "in_progress",
     "followup": {"note": "Whether the promise should be the requested date or a confirmed ship date is open question 1."},
     "definition": "The share of delivered order lines that arrived on or before the date the customer requested.",
     "calculation": {"text": "On-time delivery lines over delivered lines.", "numerator": "On-time delivery lines", "denominator": "Delivered lines"},
     "owner": {"unknown": true, "who_might_know": "VP Operations"},
     "trusted_report": {"unknown": true},
     "breakdowns": ["site"],
     "caveats": ["A delivery that never arrives cannot make this metric worse - it never enters the denominator."],
     "format": "percent", "direction": "higher_is_better"},
    {"name": "cost_per_shipment", "label": "Cost Per Shipment", "status": "in_progress",
     "definition": "Average freight cost of moving one shipment.",
     "owner": {"unknown": true, "who_might_know": "Logistics Manager"},
     "backlog": {"status": "blocked",
                 "reason": "No freight or carrier-cost source is in scope.",
                 "unblock_requires": ["A carrier or freight-audit source keyed to the X3 delivery number."]}}
  ],
  "cubes": [{"name": "mart_i2d", "description": "I2D process cube by site and month.",
             "measures": ["inventory_accuracy", "on_time_delivery_rate", "order_fill_rate"],
             "group_by": ["TimeDimension('metric_time', 'month')", "Dimension('site__site_name')"]}]
}
```

`on_time_delivery_rate` compiles to the KPI already in `metrics.yml`
(`status: provisional` with the follow-up note as its reason, `owner: TBD`,
`owner_proposed: VP Operations`), plus `requirement: O2C-M1`: O2C comes
before I2D, which shows it too. The two slots become two `process_metric.csv`
rows and one definition. `cost_per_shipment` compiles to its `backlog.yml`
entry.

## A measure's lifecycle, end to end (the Sample Project)

The requirements tool's sample workspace compiles to `projects/sample/`. Its
Cost Per Shipment needs a freight source, which the architecture first lacked:

1. **Blocked.** The engineers bind the measure with
   `backlog: {status: blocked, reason: "No freight or carrier-cost source is in scope..."}`.
   The compiler writes it to `backlog.yml`; every route answers with the reason
   instead of a number, and a golden answer proves the refusal.
2. **The architecture grows.** A freight simulator (`sources/simulators/freight.py`,
   derived from the ERP deliveries), an ingestion source, a staging adapter
   (`transform/platform/models/silver/staging/freight/`) and a registry entry
   (`sources/systems.yml`) - available to every project, no pack code.
3. **The pack implements it.** `fct_shipment` and `dim_carrier` in gold, a
   `shipment` semantic model, and the ratio in `metrics.yml` (the "how").
4. **Unblocked.** The binding drops its backlog reason. Compiling again removes
   the `backlog.yml` entry, writes the KPI's governance (`status: active`,
   `owner`, `requirement: I2D-M2`) and adds it to the cubes the workspace
   lists. The golden answers gain three queries; no existing number moves.

## What the schema can't check

A JSON Schema checks shape. The compiler checks the references, and fails on
any of these:

- a slot, tile, cube or department row naming a measure that isn't in `measures`;
- a measure or label defined twice;
- a code that isn't in `departments`, `processes` or `dimensions`;
- a bus-matrix tick, breakdown or `group_by` the semantic models can't honour.

The target's own checks then run on what it wrote: dbt parse, MetricFlow
validation, `python -m semantic.lint`, `python -m checks.blocked_words` and
the golden answers.
