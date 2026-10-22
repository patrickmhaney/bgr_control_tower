"""Shared fixtures.

Unit tests run anywhere. Tests marked `pipeline` need a built warehouse - run
`make mock run` first (CI does). Tests marked `tsql` need TSQL_URL.
"""
import os

import pytest

from core.settings import settings


def pytest_collection_modifyitems(config, items):
    built = os.path.exists(settings.warehouse_path)
    for item in items:
        if "pipeline" in item.keywords and not built and not item.get_closest_marker("isolated"):
            item.add_marker(pytest.mark.skip(reason="no warehouse - run `make run` first"))
        if "tsql" in item.keywords and not os.environ.get("TSQL_URL"):
            item.add_marker(pytest.mark.skip(reason="TSQL_URL not set"))


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    """Point every location at a fresh temporary directory."""
    monkeypatch.setenv("CT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CT_MOCK_DB", str(tmp_path / "mock_sources.duckdb"))
    monkeypatch.setenv("CT_BRONZE_ROOT", str(tmp_path / "bronze"))
    monkeypatch.setenv("CT_WAREHOUSE_PATH", str(tmp_path / "warehouse.duckdb"))
    monkeypatch.setenv("CT_EXPORTS_ROOT", str(tmp_path / "exports"))
    return tmp_path
