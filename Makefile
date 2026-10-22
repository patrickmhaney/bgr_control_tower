# The whole interface. Every target calls a step command (python -m ctl ...).
PY := uv run python

.PHONY: setup mock advance run golden test lint ui serve studio reset
setup:            ## install dependencies and dbt packages
	uv sync --all-extras
	$(PY) -m ctl dbt deps --quiet
mock:             ## synthetic sources as of the initial date
	$(PY) -m ctl sources init
advance:          ## move the sources forward: make advance DAYS=3
	$(PY) -m ctl sources advance --days $(or $(DAYS),1)
run:              ## the daily pipeline: ingest, build, cubes, serving load
	$(PY) -m ctl run
golden:           ## golden answers: semantic layer == reference SQL == frozen answers
	$(PY) -m evaluation.golden check
test:             ## unit and conformance tests
	uv run pytest -q
lint:             ## ruff, governance lint, SQL portability
	uv run ruff check .
	$(PY) -m ctl dbt compile --quiet
	$(PY) -m semantic.lint
	$(PY) -m checks.portability
ui:               ## Dagster UI on http://localhost:3000
	uv run dagster dev -m orchestration.definitions
serve:            ## data service (REST + MCP) on http://localhost:8000
	uv run uvicorn apps.data_service.app:app --port 8000
studio:           ## the Studio: the architecture and a live pipeline walk-through, http://localhost:8800
	$(PY) -m apps.studio
reset:            ## delete everything under .data/
	$(PY) -m ctl reset
