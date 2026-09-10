# BGR Control Tower

A proof of concept for a process-performance data model: nine Power BI
dashboards, one per business process, driven by metrics that are **defined
once** and mapped to dashboards through a seed.

Five mock source systems (Sage X3, HubSpot, Paycom, Netstock, Pangea) flow
through a dlt ingestion layer into a dbt star schema. Ten metrics compile from
YAML into warehouse SQL, nine dashboard views, a generated Power BI model, and a
registry an AI agent can read.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
dbt deps
export DBT_PROFILES_DIR="$PWD" BGR_CONTROL_TOWER_HOME="$PWD"

python run_ingestion.py               # source systems -> landing/ -> raw.duckdb
dbt build                             # raw -> staging -> core -> metrics -> dashboards
python scripts/compile_metrics.py     # the metric registry ask_metric.py reads
python scripts/export_powerbi.py      # Parquet + a Power BI model in exports/
python scripts/q.py                   # query anything
```

Setup details, a full teardown-and-rebuild, and troubleshooting are in
[docs/running_it.md](docs/running_it.md).

## How it fits together

```
mock_sources.duckdb            five source systems, shipped with the repo
      │  run_ingestion.py      ingestion/ - one dlt resource per source table
      ▼
landing/  ->  raw.duckdb       append-only Parquet archive, projected to raw
      │  dbt build
      ▼
staging -> intermediate -> core          5 conformed dimensions, 6 facts
      │
      │   semantic/metrics/*.yml  --scripts/compile_metrics.py-->  mtr_* models,
      │                                                            registry, catalogue
      ▼
marts/metrics (10)  ->  marts/process (9 dashboard views, via seeds/process_metric_map.csv)
      │
      ▼
exports/                       Parquet + a TMDL Power BI model (scripts/export_powerbi.py)
```

## What's where

| Path | What |
|---|---|
| `ingestion/` | The extraction spec (`config.py`), dlt resources, the landing-to-raw projection and the schema contract. `simulators/` stands in for the real source clients. |
| `models/` | dbt: `staging/` (generated), `intermediate/`, `marts/core/`, `marts/metrics/` (generated), `marts/process/` (generated). |
| `semantic/` | One YAML per metric, plus the fact-to-dimension bindings and the conformed dimensions. |
| `seeds/` | The process list, the process-to-metric map, the site crosswalk, legal suffixes, and the compiled metric registry. |
| `snapshots/`, `tests/`, `macros/` | Type 2 history, singular tests, name-matching macros. |
| `scripts/` | Generators, the query tool and checks - see below. |
| `generate_mock_sources.py`, `mock_sources.duckdb`, `schema.sql` | The mock source data, its generator, and portable DDL for it. |

| Script | What it does |
|---|---|
| `run_ingestion.py` | Source systems → landing → raw. `--explain` prints the extraction spec, `--state` the watermarks. |
| `scripts/q.py` | Query the sources, raw and the warehouse from one prompt. |
| `scripts/compile_metrics.py` | Compiles `semantic/metrics/` into the `mtr_*` models, the registry seed and JSON, and the catalogue. |
| `scripts/generate_process_views.py` | Generates the nine dashboard views from the seed map. |
| `scripts/generate_staging.py` | Generates the staging models from a column spec. |
| `scripts/freeze_schema_contract.py` | Pins the expected source schema. |
| `scripts/regenerate.py` | Runs every generator in order. `--check` fails if any generated file was stale. |
| `scripts/test_metric_parity.py` | Reconciles every metric model against its base fact, and writes the Power BI parity queries. |
| `scripts/export_powerbi.py` | Writes the Parquet export and the generated Power BI (TMDL) model. |
| `scripts/ask_metric.py` | Answers a metric question from the registry alone - the AI use case. |
| `scripts/verify_ingestion.py` | Builds via the pipeline and directly from source, and diffs the two. |
| `scripts/profile_sources.py` | Reproduces the numbers in the feasibility audit. |

## Documentation

Roughly in reading order:

| Document | Read it for |
|---|---|
| [architecture.md](docs/architecture.md) | The design: one conformed core, how a metric is added, entity resolution, what is generated. |
| [metric_feasibility.md](docs/metric_feasibility.md) | Whether each metric can be computed, and the business decision each one hides. |
| [open_questions.md](docs/open_questions.md) | What the data could not answer, what was assumed, and the cost to reverse each assumption. |
| [running_it.md](docs/running_it.md) | Hands on: run, step through, query, change. |
| [sources.md](docs/sources.md) | The five mock source systems: fidelity, grain, the cross-system join map, the deliberate data-quality landmines. |
| [ingestion.md](docs/ingestion.md) | Source systems to raw: extraction strategies, per-system difficulty, pitfalls. |
| [data_model.md](docs/data_model.md) | Diagrams: source ERDs, the star schema, the pipeline DAGs. |
| [powerbi_model.md](docs/powerbi_model.md) | The Power BI model, the I2D dashboard, and how to open it. |
| [metric_catalog.md](docs/metric_catalog.md) | Generated. Every metric's definition, grain, owner and lineage. |

## Where it stands

All ten metrics compute. Five are provisional because each waits on a business
decision recorded in [open_questions.md](docs/open_questions.md).

| Metric | Dashboard | Value | Status |
|---|---|---|---|
| On-Time Delivery | I2D | 75.6% | active |
| Cost Per Shipment | I2D | $1,564.18 | active |
| Inventory Accuracy | I2D | 93.4% | provisional |
| DSO (days-to-pay proxy) | O2C | 48.0 days | provisional |
| Return Rate | O2C | 1.27% | provisional |
| Cost Per Order | O2C | $1,560.78 | provisional |
| Match Rate | S2P | 70.7% | provisional |
| Unmatched CRM Customers | — | 11.9% | active, data quality |
| Shipment Order Reference Coverage | — | 85.4% | active, data quality |
| Unsettled Invoice Rate | — | 13.8% | active, companion to DSO |

Six of the nine dashboards have no defined metrics yet. Their views exist,
typed and empty, so the architecture is exercised against the empty case.
