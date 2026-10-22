"""The data service: governed metrics and marts over REST, and the MCP server, in one container.

    uvicorn apps.data_service.app:app --port 8000      # or: make serve

REST (contract C6, OpenAPI at /docs and /openapi.json):

    GET  /metrics                 the catalog's KPIs
    GET  /metrics/{name}          one metric: definition, governance, dimensions, dashboards
    POST /metrics/dimensions      valid group-bys for a set of metrics
    POST /query                   numbers, with status and caveats beside them
    POST /compile                 the SQL a query would run
    GET  /datasets                the marts in the serving database
    GET  /datasets/{name}         a page of one mart

MCP (Streamable HTTP) at /mcp/ - the same tools as apps/data_service/mcp_server.py.

Everything is read-only. Locally there is no auth. In Azure the container
sits behind Container Apps authentication (Entra ID), and CT_API_KEY can
additionally require an X-API-Key header for app-to-app calls.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from apps.data_service.audit import caller, record
from apps.data_service.mcp_server import mcp, service
from serving import serving_db
from serving.semantic_service import MetricRequestError


def _transport_security():
    from mcp.server.transport_security import TransportSecuritySettings

    hosts = [h for h in os.environ.get("CT_ALLOWED_HOSTS", "").split(",") if h]
    if not hosts:
        return None
    return TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=[f"https://{h}" for h in hosts])


mcp_app = mcp.streamable_http_app(streamable_http_path="/", transport_security=_transport_security())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Control Tower data service", version="2.0.0", lifespan=lifespan,
              description="Governed metrics and marts. Every number comes from the semantic layer.")


async def identify(request: Request, x_api_key: str | None = Header(default=None)):
    expected = os.environ.get("CT_API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Missing or wrong X-API-Key.")
    caller.set(request.headers.get("x-ms-client-principal-name", "local"))


class QueryRequest(BaseModel):
    metrics: list[str] = Field(examples=[["on_time_delivery_rate"]])
    group_by: list[str] = Field(default_factory=list, examples=[["site__site_name", "metric_time__month"]])
    where: list[str] = Field(default_factory=list)
    order_by: list[str] = Field(default_factory=list)
    limit: int = Field(default=1000, le=5000)
    start: str | None = None
    end: str | None = None


class DimensionsRequest(BaseModel):
    metrics: list[str]


def _refused(exc: MetricRequestError):
    return HTTPException(status_code=422, detail=str(exc))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics", dependencies=[Depends(identify)])
def list_metrics(role: str | None = "kpi"):
    return service().list_metrics(role=role)


@app.get("/metrics/{name}", dependencies=[Depends(identify)])
def describe_metric(name: str):
    try:
        return service().describe_metric(name)
    except MetricRequestError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/metrics/dimensions", dependencies=[Depends(identify)])
def dimensions(req: DimensionsRequest):
    try:
        return service().valid_dimensions(req.metrics)
    except MetricRequestError as exc:
        raise _refused(exc) from exc


@app.post("/query", dependencies=[Depends(identify)])
def query(req: QueryRequest):
    record("rest", "query", metrics=req.metrics, group_by=req.group_by)
    try:
        return service().query(req.metrics, group_by=req.group_by, where=req.where or None,
                               order_by=req.order_by or None, limit=req.limit,
                               start=req.start, end=req.end)
    except MetricRequestError as exc:
        raise _refused(exc) from exc


@app.post("/compile", dependencies=[Depends(identify)])
def compile_sql(req: QueryRequest):
    try:
        return {"sql": service().compile(req.metrics, group_by=req.group_by,
                                         where=req.where or None, limit=req.limit)}
    except MetricRequestError as exc:
        raise _refused(exc) from exc


@app.get("/datasets", dependencies=[Depends(identify)])
def datasets():
    return serving_db.list_datasets()


@app.get("/datasets/{name}", dependencies=[Depends(identify)])
def dataset(name: str, limit: int = 1000, offset: int = 0):
    record("rest", "dataset", dataset=name)
    try:
        return serving_db.read_dataset(name, limit=min(limit, 10000), offset=offset)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"No dataset {name!r}.") from exc


app.mount("/mcp", mcp_app)
