---
name: run-the-platform
description: Run, reset, advance or troubleshoot the platform locally - synthetic sources, the daily pipeline, golden answers, tests, the data service and Dagster. Use when asked to run, rebuild, demo, step through or debug the pipeline.
---

- Every target runs on one project pack: default `sample_v2`, else `make ... PROJECT=<slug>` or `python -m ctl --project <slug> ...`. `ls projects/` lists them.
- Fresh start: `make reset mock run golden`. Everything lives in `.data/<slug>/`; packs never share data.
- Simulate days of business: `make advance DAYS=n`, then `python -m ctl ingest` and `python -m ctl build` (or `make run`).
- One step at a time: `python -m ctl --help` lists every step command.
- Serve: `make serve` (REST + MCP at :8000), `make ui` (Dagster at :3000), `make studio` (the Studio at :8800; a project switcher sits in its header).
- Tests: `make test`; lint, pack layout and portability: `make lint` (includes `python -m ctl check-pack`).
- Troubleshooting table: docs/running.md, "When something breaks". A failing golden answer means a number changed - find out why before re-freezing.
