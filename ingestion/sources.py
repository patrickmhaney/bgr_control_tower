"""dlt resources: one per source table, driven entirely by ingestion/config.py.

This module is production code. It knows nothing about DuckDB or about the mock
- it asks the simulator package for rows and hands them to dlt. Swapping the
simulators for real clients does not change a line in here.

Watermarks live in dlt's own pipeline state (`dlt.current.resource_state()`),
so they survive across runs and are stored with the pipeline rather than in a
file somebody can delete. Every windowed read applies a lookback before using
its watermark - see config.DEFAULT_LOOKBACK_DAYS for why.
"""
from __future__ import annotations

import datetime as dt

import dlt

from . import contract
from .config import SOURCES, SourceSpec, Strategy, TableSpec
from .simulators import netstock_api, paycom_sftp
from .simulators import erp_database as erp
from .simulators.hubspot_api import HubSpotClient
from .simulators.pangea_api import PangeaClient


def _window_start(spec: TableSpec, full_refresh: bool) -> dt.date | None:
    """Resolve the watermark for a windowed read, minus the lookback.

    Returns None on a first run or when a full refresh is forced, which the
    simulators interpret as "no predicate" - the backfill path.
    """
    if full_refresh:
        return None
    state = dlt.current.resource_state()
    high_water = state.get("high_water_mark")
    if high_water is None:
        return None
    if isinstance(high_water, str):
        high_water = dt.date.fromisoformat(high_water)
    return high_water - dt.timedelta(days=spec.lookback_days)


def _record_high_water(rows: list[dict], column: str) -> None:
    seen = [r[column] for r in rows if r.get(column) is not None]
    if not seen:
        return
    highest = max(seen)
    if isinstance(highest, dt.datetime):
        highest = highest.date()
    state = dlt.current.resource_state()
    previous = state.get("high_water_mark")
    if isinstance(previous, str):
        previous = dt.date.fromisoformat(previous)
    state["high_water_mark"] = max(highest, previous).isoformat() if previous else highest.isoformat()


def _resource(spec: TableSpec, fetch, source_name: str):
    """Wrap a fetch callable as a dlt resource carrying the right disposition.

    The column hints come from the pinned schema contract rather than from
    inference. Without them a column that is null on every row of an extract
    is silently dropped - which is exactly what happened to
    paycom.employee.rehire_date and manager_ee_id on the first run here.
    """
    return dlt.resource(
        fetch,
        name=spec.name,
        columns=contract.columns_for(source_name, spec.name),
        # Landing is append-only: every extract is preserved so the warehouse
        # can be rebuilt from the archive without touching the source again.
        # Deduplication to current state happens in the load step, driven by
        # spec.write_disposition.
        write_disposition="append",
        primary_key=list(spec.primary_key) or None,
    )


# ---------------------------------------------------------------------------
# Sage X3
# ---------------------------------------------------------------------------
@dlt.source(name="sage_x3")
def sage_x3_source(full_refresh: bool = False):
    spec_source: SourceSpec = SOURCES["sage_x3"]

    def make(spec: TableSpec):
        def fetch():
            if spec.strategy is Strategy.FULL_REFRESH:
                rows = erp.read_full(spec.name)
            elif spec.strategy is Strategy.MODIFIED_DATE:
                since = _window_start(spec, full_refresh)
                rows = erp.read_modified_since(spec.name, spec.cursor_column, since)
                _record_high_water(rows, spec.cursor_column)
            elif spec.strategy is Strategy.HEADER_WINDOW:
                parent, join_column, parent_date = spec.window_via
                since = _window_start(spec, full_refresh)
                rows = erp.read_header_window(
                    spec.name, parent, join_column, parent_date, since)
                if parent == spec.name:
                    _record_high_water(rows, parent_date)
                else:
                    # The child has no date, so the watermark comes from the
                    # parent rows that were in scope. Read it directly rather
                    # than inferring it from the child.
                    parent_rows = erp.read_header_window(
                        parent, parent, join_column, parent_date, since)
                    _record_high_water(parent_rows, parent_date)
            else:
                raise ValueError(f"unsupported strategy {spec.strategy} for X3")
            yield from rows
        return _resource(spec, fetch, "sage_x3")

    for spec in spec_source.tables:
        yield make(spec)


# ---------------------------------------------------------------------------
# HubSpot
# ---------------------------------------------------------------------------
@dlt.source(name="hubspot")
def hubspot_source(full_refresh: bool = False):
    client = HubSpotClient()

    def make(spec: TableSpec):
        def fetch():
            if spec.strategy is Strategy.API_CURSOR:
                since = _window_start(spec, full_refresh)
                rows = list(client.list_objects(
                    spec.name, modified_since=since,
                    cursor_column=spec.cursor_column, include_archived=True,
                    order_by=list(spec.primary_key)))
                _record_high_water(rows, spec.cursor_column)
            else:
                rows = list(client.list_objects(
                    spec.name, include_archived=True,
                    order_by=list(spec.primary_key)))
            yield from rows
        return _resource(spec, fetch, "hubspot")

    for spec in SOURCES["hubspot"].tables:
        yield make(spec)


# ---------------------------------------------------------------------------
# Paycom
# ---------------------------------------------------------------------------
@dlt.source(name="paycom")
def paycom_source(as_of: dt.date | None = None):
    """Every table is a full-refresh file pickup. There is no other option."""
    def make(spec: TableSpec):
        def fetch():
            yield from paycom_sftp.read_latest(spec.name, as_of=as_of)
        return _resource(spec, fetch, "paycom")

    for spec in SOURCES["paycom"].tables:
        yield make(spec)


# ---------------------------------------------------------------------------
# Netstock
# ---------------------------------------------------------------------------
@dlt.source(name="netstock")
def netstock_source():
    def make(spec: TableSpec):
        def fetch():
            yield from netstock_api.fetch(spec.name)
        return _resource(spec, fetch, "netstock")

    for spec in SOURCES["netstock"].tables:
        yield make(spec)


# ---------------------------------------------------------------------------
# Pangea
# ---------------------------------------------------------------------------
@dlt.source(name="pangea")
def pangea_source(full_refresh: bool = False):
    client = PangeaClient()
    shipment_spec = next(t for t in SOURCES["pangea"].tables if t.name == "shipment")

    # Shipments are read once and their ids reused for the children, so the
    # child reads cannot drift out of step with the parent window.
    shipments_in_scope: dict[str, list] = {}

    def fetch_shipments():
        since = _window_start(shipment_spec, full_refresh)
        rows = list(client.list_shipments(created_since=since))
        shipments_in_scope["ids"] = [r["shipment_id"] for r in rows]
        _record_high_water(rows, shipment_spec.cursor_column)
        yield from rows

    def make_child(spec: TableSpec):
        def fetch():
            ids = shipments_in_scope.get("ids")
            if ids is None:
                # Child selected without its parent: fall back to a full read
                # rather than silently returning nothing.
                yield from client.fetch(spec.name)
                return
            yield from client.children_for(spec.name, ids)
        return _resource(spec, fetch, "pangea")

    def make_reference(spec: TableSpec):
        def fetch():
            yield from client.fetch(spec.name)
        return _resource(spec, fetch, "pangea")

    yield _resource(shipment_spec, fetch_shipments, "pangea")
    for spec in SOURCES["pangea"].tables:
        if spec.name == "shipment":
            continue
        if spec.strategy is Strategy.HEADER_WINDOW:
            yield make_child(spec)
        else:
            yield make_reference(spec)


BUILDERS = {
    "sage_x3": sage_x3_source,
    "hubspot": hubspot_source,
    "paycom": paycom_source,
    "netstock": netstock_source,
    "pangea": pangea_source,
}
