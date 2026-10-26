"""The metric query service: the one module that talks to the semantic engine.

    svc = SemanticService()                       # MetricFlow over the DuckDB warehouse
    svc.list_metrics()
    svc.describe_metric("on_time_delivery_rate")
    svc.valid_dimensions(["on_time_delivery_rate"])
    svc.query(["on_time_delivery_rate"], group_by=["site__site_name", "metric_time__month"])

The MCP server, the REST API, the mart materializer and the golden-answer
tests all call this, and nothing else imports MetricFlow (contract C6, rule 5
in PLAN.md §9.3). Swapping the semantic engine means reimplementing this
module, not its consumers.

Two backends:

duckdb   MetricFlow renders DuckDB SQL and runs it against the warehouse file,
         read-only.
tsql     MetricFlow has no T-SQL renderer, so it renders Postgres-style SQL,
         sqlglot translates it to T-SQL, and pymssql runs it on SQL Server,
         Azure SQL or a managed instance. This is what keeps MetricFlow usable
         if a Microsoft warehouse wins the evaluation (decision D10). Set
         TSQL_URL to mssql://user:password@host:port/database.

Governance travels with every answer: a metric's status, owner and caveats
come back beside its numbers, a backlog metric (placeholder or blocked)
returns its reason and no number, and an invalid dimension is refused with
the list of dimensions that are valid.
"""
from __future__ import annotations

import datetime as dt
import decimal
import os
from dataclasses import dataclass, field
from functools import cached_property
from urllib.parse import urlparse

import duckdb

from core import project
from core.settings import settings

DEFAULT_ROW_LIMIT = 5000


class MetricRequestError(ValueError):
    """A request the semantic layer refuses, with a reason a person or agent can act on."""


def _cell(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, dt.datetime):
        return v
    if isinstance(v, dt.date):
        return dt.datetime(v.year, v.month, v.day)
    return v


# ---------------------------------------------------------------------------
# SQL clients MetricFlow runs through
# ---------------------------------------------------------------------------
class _BaseClient:
    def execute(self, stmt, sql_bind_parameter_set=None):
        self.query(stmt)

    def dry_run(self, stmt, sql_bind_parameter_set=None):
        self.query(f"select * from ({stmt}) as dry_run where 1 = 0")

    def render_bind_parameter_key(self, key: str) -> str:
        return f"${key}"

    def _table(self, columns, rows):
        from metricflow.data_table.mf_table import MetricFlowDataTable

        return MetricFlowDataTable.create_from_rows(
            column_names=columns, rows=[tuple(_cell(v) for v in r) for r in rows])


class DuckDBClient(_BaseClient):
    def __init__(self, path: str):
        self.path = path

    @property
    def sql_engine_type(self):
        from metricflow.protocols.sql_client import SqlEngine

        return SqlEngine.DUCKDB

    @cached_property
    def sql_plan_renderer(self):
        from metricflow.sql.render.duckdb_renderer import DuckDbSqlPlanRenderer

        return DuckDbSqlPlanRenderer()

    def query(self, stmt, sql_bind_parameter_set=None):
        con = duckdb.connect(self.path, read_only=True)
        try:
            cur = con.execute(stmt)
            return self._table([d[0] for d in cur.description], cur.fetchall())
        finally:
            con.close()

    def close(self):
        pass


class TsqlClient(_BaseClient):
    """MetricFlow's Postgres-style SQL, translated to T-SQL by sqlglot."""

    def __init__(self, url: str, database: str | None = None):
        self.url = urlparse(url)
        self.database = database or self.url.path.lstrip("/")

    @property
    def sql_engine_type(self):
        from metricflow.protocols.sql_client import SqlEngine

        return SqlEngine.POSTGRES

    @cached_property
    def sql_plan_renderer(self):
        from metricflow.sql.render.postgres import PostgresSQLSqlPlanRenderer

        return PostgresSQLSqlPlanRenderer()

    def translate(self, stmt: str) -> str:
        return to_tsql(stmt, self.database)

    def query(self, stmt, sql_bind_parameter_set=None):
        import pymssql

        con = pymssql.connect(server=self.url.hostname, port=self.url.port or 1433,
                              user=self.url.username, password=self.url.password,
                              database=self.database)
        try:
            cur = con.cursor()
            cur.execute(self.translate(stmt))
            return self._table([d[0] for d in cur.description], cur.fetchall())
        finally:
            con.close()

    def close(self):
        pass


def to_tsql(stmt: str, database: str | None = None) -> str:
    """Translate MetricFlow's Postgres-style SQL to T-SQL.

    The warehouse catalog name in MetricFlow's table references is replaced
    with the target database (or dropped), since a SQL Server database is
    rarely called `warehouse`.
    """
    import sqlglot
    from sqlglot import exp

    tree = sqlglot.parse_one(stmt, read="postgres")
    for table in tree.find_all(exp.Table):
        if table.args.get("catalog") is not None:
            table.set("catalog", exp.to_identifier(database) if database else None)
    return tree.sql(dialect="tsql", unsupported_level=sqlglot.ErrorLevel.RAISE)


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------
@dataclass
class SemanticService:
    backend: str = "duckdb"
    warehouse_path: str = field(default_factory=lambda: settings.warehouse_path)
    manifest_path: str = field(default_factory=lambda: project.current().semantic_manifest)
    tsql_url: str | None = field(default_factory=lambda: os.environ.get("TSQL_URL"))

    @cached_property
    def client(self):
        if self.backend == "tsql":
            if not self.tsql_url:
                raise RuntimeError("The tsql backend needs TSQL_URL.")
            return TsqlClient(self.tsql_url)
        return DuckDBClient(self.warehouse_path)

    @cached_property
    def engine(self):
        import logging

        from metricflow.engine.metricflow_engine import MetricFlowEngine
        from metricflow_semantics.model.dbt_manifest_parser import (
            parse_manifest_from_dbt_generated_manifest,
        )
        from metricflow_semantics.model.semantic_manifest_lookup import SemanticManifestLookup

        for noisy in ("metricflow", "metricflow_semantics", "dbt_metricflow"):
            logging.getLogger(noisy).setLevel(logging.ERROR)
        if not os.path.exists(self.manifest_path):
            raise RuntimeError("No semantic manifest. Run `python -m ctl dbt parse` first.")
        with open(self.manifest_path) as fh:
            manifest = parse_manifest_from_dbt_generated_manifest(manifest_json_string=fh.read())
        return MetricFlowEngine(semantic_manifest_lookup=SemanticManifestLookup(manifest),
                                sql_client=self.client)

    @cached_property
    def catalog(self) -> dict[str, dict]:
        from semantic.catalog import build_catalog

        return {m["name"]: m for m in build_catalog(self)}

    # -- discovery ----------------------------------------------------------
    def list_metrics(self, role: str | None = "kpi") -> list[dict]:
        """Every metric in the catalog: name, label, status, owner, description."""
        keys = ("name", "label", "status", "owner", "description", "role", "format", "source")
        return [{k: m.get(k) for k in keys} for m in self.catalog.values()
                if role is None or m.get("role") == role]

    def describe_metric(self, name: str) -> dict:
        """The full catalog entry: definition, governance, valid dimensions, dashboards."""
        if name not in self.catalog:
            raise MetricRequestError(
                f"Unknown metric {name!r}. Known metrics: {', '.join(sorted(self.catalog))}")
        return self.catalog[name]

    def metric_dimensions(self, name: str) -> list[str]:
        """Group-by names valid for one MetricFlow metric. Used by the catalog."""
        names = set()
        for d in self.engine.list_dimensions([name]):
            qualified = d.granularity_free_dunder_name
            if d.type.value.lower() == "time":
                for grain in ("day", "week", "month", "quarter", "year",
                              "fiscal_quarter", "fiscal_year"):
                    names.add(f"{qualified}__{grain}")
            else:
                names.add(qualified)
        return sorted(names)

    def valid_dimensions(self, metrics: list[str]) -> list[str]:
        """Group-by names valid for every one of these metrics together."""
        common: set[str] | None = None
        for m in metrics:
            entry = self.describe_metric(m)
            dims = set(entry.get("valid_dimensions") or [])
            common = dims if common is None else common & dims
        return sorted(common or [])

    # -- querying -----------------------------------------------------------
    def _check(self, metrics: list[str], group_by: list[str]) -> list[dict]:
        if not metrics:
            raise MetricRequestError("Ask for at least one metric.")
        entries = [self.describe_metric(m) for m in metrics]
        for e in entries:
            if e["source"] == "backlog":
                reason = e.get("blocked_reason") or e.get("placeholder_reason")
                raise MetricRequestError(
                    f"{e['label']} has no number: it is {e['status']}. {reason}".strip())
        valid = set(self.valid_dimensions(metrics))
        bad = [g for g in group_by if g not in valid]
        if bad:
            raise MetricRequestError(
                f"{', '.join(metrics)} cannot be grouped by {', '.join(bad)}. "
                f"Valid dimensions: {', '.join(sorted(valid))}")
        return entries

    def _request(self, metrics, group_by, where, order_by, limit, start, end):
        from metricflow.engine.metricflow_engine import MetricFlowQueryRequest

        return MetricFlowQueryRequest.create(
            metric_names=metrics, group_by_names=group_by or None,
            where_constraints=where or None, order_by_names=order_by or None,
            limit=limit,
            time_constraint_start=dt.datetime.fromisoformat(start) if start else None,
            time_constraint_end=dt.datetime.fromisoformat(end) if end else None)

    def compile(self, metrics: list[str], group_by: list[str] | None = None,
                where: list[str] | None = None, order_by: list[str] | None = None,
                limit: int | None = None, start: str | None = None,
                end: str | None = None) -> str:
        """The SQL that would run, in the backend's dialect."""
        group_by = group_by or []
        self._check(metrics, group_by)
        result = self.engine.explain(self._request(metrics, group_by, where, order_by,
                                                   limit, start, end))
        sql = result.sql_statement.sql
        return self.client.translate(sql) if self.backend == "tsql" else sql

    def query(self, metrics: list[str], group_by: list[str] | None = None,
              where: list[str] | None = None, order_by: list[str] | None = None,
              limit: int | None = DEFAULT_ROW_LIMIT, start: str | None = None,
              end: str | None = None) -> dict:
        """Numbers plus the governance that travels with them."""
        group_by = group_by or []
        entries = self._check(metrics, group_by)
        if end is None and any(e.get("type") == "cumulative" for e in entries):
            end = self.as_of_date().isoformat()      # a rolling window must not run past the data
        try:
            result = self.engine.query(self._request(metrics, group_by, where, order_by,
                                                     limit, start, end))
        except Exception as exc:  # MetricFlow's errors are long; keep the first line
            raise MetricRequestError(str(exc).strip().splitlines()[0]) from exc
        table = result.result_df
        rows = [[(v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else v) for v in r]
                for r in table.rows]
        return {
            "columns": list(table.column_names),
            "rows": rows,
            "metrics": [{k: e.get(k) for k in ("name", "label", "status", "owner", "caveats",
                                                "provisional_reason", "format")}
                        for e in entries],
            "sql": result.sql,
        }

    def as_of_date(self) -> dt.date:
        """The latest date the data covers: the most recent delivery shipped."""
        con = duckdb.connect(self.warehouse_path, read_only=True)
        try:
            return con.execute("select max(ship_date) from gold.fct_delivery_line").fetchone()[0]
        finally:
            con.close()
