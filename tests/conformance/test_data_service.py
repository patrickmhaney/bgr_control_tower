"""Contract C6 conformance: the REST API and the MCP tools."""
import json

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.pipeline

EXPECTED_ROUTES = {"/metrics", "/metrics/{name}", "/metrics/dimensions", "/query", "/compile",
                   "/datasets", "/datasets/{name}", "/health"}
EXPECTED_TOOLS = {"list_metrics", "describe_metric", "valid_dimensions", "query_metrics", "explain_sql"}


@pytest.fixture(scope="module")
def client(monkeypatch_module=None):
    import os

    os.environ["CT_ALLOWED_HOSTS"] = "testserver"
    import importlib

    import apps.data_service.app as app_module
    importlib.reload(app_module)
    with TestClient(app_module.app) as c:
        yield c


def test_openapi_exposes_the_contract(client):
    paths = set(client.get("/openapi.json").json()["paths"])
    assert EXPECTED_ROUTES <= paths


def _catalog():
    from semantic.catalog import build_catalog
    from serving.semantic_service import SemanticService

    return build_catalog(SemanticService())


def test_query_carries_governance(client):
    import duckdb

    from core.settings import settings

    provisional = next(e for e in _catalog() if e["status"] == "provisional"
                       and "site__site_name" in e["valid_dimensions"])
    r = client.post("/query", json={"metrics": [provisional["name"]], "group_by": ["site__site_name"]})
    assert r.status_code == 200
    body = r.json()
    assert body["metrics"][0]["status"] == "provisional"
    assert body["metrics"][0]["provisional_reason"]
    with duckdb.connect(settings.warehouse_path, read_only=True) as con:
        sites = con.execute("select count(distinct site_name) from gold.dim_site").fetchone()[0]
    assert len(body["rows"]) <= sites


def test_invalid_requests_are_refused_with_reasons(client):
    catalog = _catalog()
    narrow = next(e for e in catalog if e["source"] == "metricflow" and e["role"] == "kpi"
                  and "employee__department_name" not in e["valid_dimensions"])
    r = client.post("/query", json={"metrics": [narrow["name"]], "group_by": ["employee__department_name"]})
    assert r.status_code == 422 and "Valid dimensions" in r.json()["detail"]
    waiting = next(e for e in catalog if e["source"] == "backlog")
    r = client.post("/query", json={"metrics": [waiting["name"]]})
    assert r.status_code == 422 and waiting["status"] in r.json()["detail"]


def test_datasets_are_served(client):
    import re

    names = client.get("/datasets").json()
    cube = next(n for n in names if re.fullmatch(r"mart_[a-z]2[a-z]", n))
    page = client.get(f"/datasets/{cube}?limit=5").json()
    assert page["columns"][0] == "metric_time__month" and len(page["rows"]) == 5


def test_mcp_lists_the_governed_tools(client):
    h = {"Accept": "application/json, text/event-stream"}
    init = client.post("/mcp/", headers=h, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "test", "version": "1"}}})
    h["mcp-session-id"] = init.headers["mcp-session-id"]
    h["mcp-protocol-version"] = "2025-06-18"
    client.post("/mcp/", headers=h, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    r = client.post("/mcp/", headers=h, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    body = r.text
    data = json.loads(body.split("data: ", 1)[1]) if "data: " in body else r.json()
    assert {t["name"] for t in data["result"]["tools"]} == EXPECTED_TOOLS
