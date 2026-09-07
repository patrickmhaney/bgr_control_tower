# Documentation index

| Document | Read it for |
|---|---|
| [running_it.md](running_it.md) | **Hands on.** How to run the pipeline, step through it, and query the result. Start here if you want to poke at the data. |
| [architecture.md](architecture.md) | **Start here.** The model, the metric-addition runbook, entity resolution, and what is generated vs hand-written. |
| [ingestion.md](ingestion.md) | Source systems to raw: the extraction spec, per-system difficulty, and the pitfalls that actually bit during the build. |
| [data_model.md](data_model.md) | ERDs for the five source systems and the star schema, the cross-system join map with measured match rates, and the pipeline DAGs. |
| [metric_feasibility.md](metric_feasibility.md) | Phase 0. Whether each of the seven defined metrics can actually be computed. Three cannot. |
| [open_questions.md](open_questions.md) | The ten things the data could not answer, what was assumed, and the cost to reverse each. |
| [semantic_layer_spike.md](semantic_layer_spike.md) | Whether one metric definition can generate both the SQL and the Power BI measures. It can. |
| [metric_catalog.md](metric_catalog.md) | Generated. Every metric with its definition, grain, owner and lineage. |
| [powerbi_model.md](powerbi_model.md) | The semantic model, the I2D dashboard, and one-model-vs-nine. |

## Scripts

| Script | What it does |
|---|---|
| `run_ingestion.py` | Source systems → landing → raw. `--explain` prints the spec, `--state` shows the watermarks. |
| `scripts/q.py` | Query anything. Attaches source, raw and warehouse read-only under one prompt. |
| `scripts/freeze_schema_contract.py` | Pin the expected source schema. Run once, review, commit. |
| `scripts/test_metric_parity.py` | Reconcile every metric between its pre-aggregated model and its base fact. Emits the Power BI parity gate. |
| `scripts/update_build_stats.py` | Rewrite the generated build statistics in the docs. `--check` in CI. |
| `scripts/regenerate.py` | Run every generator in dependency order. `--check` is the CI guard against stale generated files. |
| `scripts/verify_ingestion.py` | Prove the pipeline is lossless by building both ways and diffing. |
| `scripts/profile_sources.py` | Reproduces every number quoted in the feasibility audit. Read-only, no dbt needed. |
| `scripts/generate_staging.py` | Regenerates the 46 staging models from the column spec. |
| `scripts/compile_metrics.py` | Compiles the metric registry into 8 artefacts. `--check` validates without writing. |
| `scripts/generate_process_views.py` | Regenerates the 9 process views from the seed map. |
| `scripts/export_powerbi.py` | Parquet export plus the complete generated TMDL model. |
| `scripts/test_metric_reuse.py` | Asserts that one metric can serve two dashboards from one definition. |
| `scripts/ask_metric.py` | Answers a metric question from the registry alone - the AI use case, demonstrated. |

Generated artefacts live in `exports/`:

```
exports/
  parquet/                       Power BI import data
  powerbi/
    measures.dax                 measures only, for a hand-built model
    tmdl/                        measure fragments per table
    model/definition/            the complete generated TMDL model
  cube/model/cubes/              Cube schema, if that route is taken
  semantic/metric_registry.json  the contract an AI agent reads
  export_manifest.json           what was exported, and how many rows
```
