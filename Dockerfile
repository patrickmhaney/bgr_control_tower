# One image for both container apps: Dagster (the pipeline) and the data service.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra tsql --no-install-project

COPY . .
RUN uv sync --frozen --no-dev --extra tsql
ENV PATH="/app/.venv/bin:$PATH" DBT_PROFILES_DIR=/app/transform
# Resolve dbt packages and compile the manifest Dagster and MetricFlow read.
RUN cd transform && dbt deps --quiet && CT_DBT_TARGET=local dbt parse --quiet

# Default: the data service. The Dagster app overrides the command with
# orchestration/entrypoint.sh.
EXPOSE 8000 3000
CMD ["uvicorn", "apps.data_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
