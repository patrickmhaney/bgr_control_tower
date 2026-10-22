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


def test_query_carries_governance(client):
    r = client.post("/query", json={"metrics": ["return_rate"], "group_by": ["site__site_name"]})
    assert r.status_code == 200
    body = r.json()
    assert body["metrics"][0]["status"] == "provisional"
    assert body["metrics"][0]["provisional_reason"]
    assert len(body["rows"]) == 3


def test_invalid_requests_are_refused_with_reasons(client):
    r = client.post("/query", json={"metrics": ["dso_days_to_pay_proxy"],
                                    "group_by": ["employee__department_name"]})
    assert r.status_code == 422 and "Valid dimensions" in r.json()["detail"]
    r = client.post("/query", json={"metrics": ["cost_per_shipment"]})
    assert r.status_code == 422 and "blocked" in r.json()["detail"]


def test_datasets_are_served(client):
    names = client.get("/datasets").json()
    assert "mart_o2c" in names
    page = client.get("/datasets/mart_o2c?limit=5").json()
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
