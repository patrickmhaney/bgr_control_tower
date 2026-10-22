"""The MCP server: governed metrics as tools for any MCP-capable agent.

    python -m apps.data_service.mcp_server          # stdio, for Claude Code / Claude Desktop

The same server is mounted at /mcp in the data service for remote agents
(Streamable HTTP). Every tool goes through the semantic service, so an agent
can only reach governed metrics: it cannot write SQL against the warehouse,
cannot cut a metric by a dimension it does not support, gets the caveats and
status with every number, and gets a reason instead of a number for a metric
that is blocked or not yet defined.
"""
from __future__ import annotations

import os
from functools import lru_cache

from mcp.server.mcpserver import MCPServer

from apps.data_service.audit import record
from serving.semantic_service import MetricRequestError, SemanticService

INSTRUCTIONS = """\
Governed business metrics. Start with list_metrics, then describe_metric to see a
metric's definition, status and caveats, and valid_dimensions before grouping.
Group-by names look like site__site_name or metric_time__month (grains: day, week,
month, quarter, year, fiscal_quarter, fiscal_year). Always report a metric's status
and caveats with its numbers. A provisional metric is a working definition with an
open business decision; say so."""

mcp = MCPServer(name="control-tower", instructions=INSTRUCTIONS)


@lru_cache(maxsize=1)
def service() -> SemanticService:
    return SemanticService(backend=os.environ.get("CT_SEMANTIC_BACKEND", "duckdb"))


@mcp.tool()
def list_metrics() -> list[dict]:
    """List every business metric: name, label, status, owner and a description."""
    return service().list_metrics()


@mcp.tool()
def describe_metric(name: str) -> dict:
    """A metric's definition, status, owner, caveats, valid dimensions and the dashboards it is on."""
    try:
        return service().describe_metric(name)
    except MetricRequestError as exc:
        return {"error": str(exc)}


@mcp.tool()
def valid_dimensions(metrics: list[str]) -> list[str] | dict:
    """The group-by names every one of these metrics supports together."""
    try:
        return service().valid_dimensions(metrics)
    except MetricRequestError as exc:
        return {"error": str(exc)}


@mcp.tool()
def query_metrics(metrics: list[str], group_by: list[str] | None = None,
                  where: list[str] | None = None, order_by: list[str] | None = None,
                  limit: int = 200, start: str | None = None, end: str | None = None) -> dict:
    """Query metrics, optionally grouped by dimensions, with status and caveats beside the numbers.

    where: MetricFlow filters, e.g. "{{ Dimension('site__site_name') }} = 'Reno NV Distribution Center'".
    order_by: names, prefix with '-' for descending, e.g. "-metric_time__month".
    start/end: ISO dates bounding metric_time.
    """
    record("mcp", "query_metrics", metrics=metrics, group_by=group_by)
    try:
        result = service().query(metrics, group_by=group_by, where=where, order_by=order_by,
                                 limit=min(limit, 5000), start=start, end=end)
        result.pop("sql", None)
        return result
    except MetricRequestError as exc:
        return {"error": str(exc)}


@mcp.tool()
def explain_sql(metrics: list[str], group_by: list[str] | None = None) -> dict:
    """The SQL the semantic layer would run for this request - for transparency, not for editing."""
    try:
        return {"sql": service().compile(metrics, group_by=group_by)}
    except MetricRequestError as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    mcp.run("stdio")
