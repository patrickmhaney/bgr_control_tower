---
name: add-source-table
description: Bring a new source table (Sage X3, HubSpot or Netstock) through the platform - extraction spec, mock data, frozen schema, bronze, staging - without breaking contracts C1/C2. Use when asked to ingest, land or model a new source table or column.
---

Specs, schemas and bronze belong to a project pack (`projects/<slug>/`, run with `CT_PROJECT=<slug>`); the generator and staging adapters are the architecture, shared by every project. A new source *system* is a new simulator in `sources/simulators/` plus a staging adapter folder in `transform/platform/`, never pack code.

1. Add the table to `projects/<slug>/ingestion/specs/<source>.yml` with its keys and a note on how it changes (C1). X3 tables use CDC; HubSpot needs a strategy and cursor; Netstock is a snapshot.
2. If the mock lacks it, generate it in `sources/generate.py` (project choices - volumes, names, sites - go in the pack's `scenario.yml`) (respect the clock: anything dated after `as_of` must be removed or rolled back in `state_as_of`), add its keys to `X3_KEYS` in `sources/clock.py` for X3 tables, then `make mock`.
3. `python -m ingestion.run --source <source> --freeze-schemas` and review the diff in `projects/<slug>/ingestion/schemas/` - that file is contract C2.
4. Add the table to `projects/<slug>/models/bronze/_bronze__sources.yml` and a one-line `bronze_<source>__<table>.sql` calling `platform.bronze_current` with its keys (`python -m ctl check-pack` requires one bronze model per spec table).
5. Add a staging model in `transform/platform/models/silver/staging/<source>/` (cleaning only: `clean_str`, `x3_date`, casts; unquoted identifiers) and its tests in the source's `_models.yml`.
6. `python -m ctl build`, `python -m ctl check-pack`, `python -m checks.portability`, and `uv run pytest tests/conformance/test_ingestion_convergence.py`.
