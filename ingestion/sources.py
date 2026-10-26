"""dlt sources, one per system, built entirely from the project pack's C1 specs.

This module is production code. It knows nothing about the mock: it asks the
client modules in sources/simulators/ for rows, and swapping those for real
clients changes nothing here.

Every row lands in bronze with four metadata columns (contract C2):

    _op            S snapshot, I insert, U upsert/update, D delete
    _change_seq    orders the rows of one table: the CDC LSN for X3, the
                   extraction timestamp elsewhere
    _extracted_at  when the extract ran (UTC)
    _dlt_load_id   added by dlt

Bronze is append-only. Turning the changelog into current state is the job of
the `bronze_current` dbt macro, so a replayed or partial extract can never
corrupt it.
"""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field

import dlt
import yaml

from core import project
from sources.simulators import azure_cost as cost_client
from sources.simulators import freight as freight_client
from sources.simulators import netstock as ns_client
from sources.simulators import sage_x3 as x3_client
from sources.simulators.hubspot import HubSpotClient

SNAPSHOT_SEQ_SUFFIX = "F" * 20


@dataclass
class TableSpec:
    name: str
    keys: list[str]
    strategy: str
    cursor: str | None = None
    reconcile_keys: str = "never"
    note: str = ""


@dataclass
class SourceSpec:
    source: str
    system: str
    tables: dict[str, TableSpec] = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


def load_spec(source: str) -> SourceSpec:
    with open(os.path.join(project.current().specs, f"{source}.yml")) as fh:
        raw = yaml.safe_load(fh)
    default = raw.get("strategy")
    tables = {
        name: TableSpec(name=name, keys=t["keys"], strategy=t.get("strategy", default),
                        cursor=t.get("cursor"), reconcile_keys=t.get("reconcile_keys", "never"),
                        note=t.get("note", ""))
        for name, t in raw["tables"].items()
    }
    return SourceSpec(source=raw["source"], system=raw["system"], tables=tables, raw=raw)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _stamp(rows, op: str, seq: str, extracted_at: dt.datetime):
    for r in rows:
        r["_op"] = op
        r["_change_seq"] = seq
        r["_extracted_at"] = extracted_at
        yield r


def _resource(fetch, spec: TableSpec):
    return dlt.resource(fetch, name=spec.name, write_disposition="append",
                        table_format="delta")


# ---------------------------------------------------------------------------
# Sage X3: snapshot once, then CDC by LSN
# ---------------------------------------------------------------------------
OP_MAP = {1: "D", 2: "I", 4: "U"}   # 3 is the update before-image; bronze keeps after-images


@dlt.source(name="sage_x3")
def sage_x3_source(full_refresh: bool = False, tables: list[str] | None = None):
    spec = load_spec("sage_x3")

    def make(t: TableSpec):
        def fetch():
            state = dlt.current.resource_state()
            watermark = state.get("lsn")
            extracted_at = _now()
            gap = watermark is not None and int(watermark, 16) < int(x3_client.min_lsn(), 16) - 1
            if full_refresh or watermark is None or gap:
                # A first run, a forced refresh, or changes purged before we
                # read them (an outage longer than CDC retention). Take a
                # fresh snapshot; bronze_current starts again from it.
                rows, lsn = x3_client.snapshot(t.name)
                state["lsn"] = lsn
                state["snapshots"] = state.get("snapshots", 0) + 1
                if gap:
                    state["resnapshots_after_gap"] = state.get("resnapshots_after_gap", 0) + 1
                yield from _stamp(rows, "S", lsn + SNAPSHOT_SEQ_SUFFIX, extracted_at)
                return
            up_to = x3_client.max_lsn()
            for r in x3_client.changes(t.name, watermark, up_to):
                op = OP_MAP.get(r.pop("__$operation"))
                lsn, seqval = r.pop("__$start_lsn"), r.pop("__$seqval")
                r.pop("__$update_mask", None)
                if op is None:
                    continue
                r["_op"], r["_change_seq"], r["_extracted_at"] = op, lsn + seqval, extracted_at
                yield r
            state["lsn"] = up_to
        return _resource(fetch, t)

    for t in spec.tables.values():
        if tables is None or t.name in tables:
            yield make(t)


# ---------------------------------------------------------------------------
# HubSpot: modified-since cursor, archived pass, key reconciliation
# ---------------------------------------------------------------------------
@dlt.source(name="hubspot")
def hubspot_source(full_refresh: bool = False, reconcile: bool = False,
                   tables: list[str] | None = None):
    spec = load_spec("hubspot")
    lookback = dt.timedelta(days=spec.raw.get("lookback_days", 1))
    client = HubSpotClient()

    def make(t: TableSpec):
        def fetch():
            state = dlt.current.resource_state()
            extracted_at = _now()
            seq = extracted_at.isoformat()
            if t.strategy == "full_refresh":
                yield from _stamp(client.list_objects(t.name, order_by=t.keys), "S", seq,
                                  extracted_at)
                return
            high_water = None if full_refresh else state.get("high_water")
            since = (dt.date.fromisoformat(high_water) - lookback) if high_water else None
            seen = []
            for r in client.list_objects(t.name, order_by=t.keys, modified_since=since,
                                         cursor=t.cursor):
                seen.append(r[t.cursor])
                if t.reconcile_keys != "never":
                    state.setdefault("keys", {})[str(r[t.keys[0]])] = True
                r.update(_op="U", _change_seq=seq, _extracted_at=extracted_at)
                yield r
            if seen:
                top = max(v.date() if isinstance(v, dt.datetime) else v for v in seen)
                state["high_water"] = max(top.isoformat(), high_water or "")
            if reconcile and t.reconcile_keys != "never":
                live = {str(k) for k in client.list_ids(t.name, t.keys[0])}
                known = state.setdefault("keys", {})
                for gone in sorted(set(known) - live):
                    del known[gone]
                    yield {t.keys[0]: gone, "_op": "D", "_change_seq": seq,
                           "_extracted_at": extracted_at}
        return _resource(fetch, t)

    for t in spec.tables.values():
        if tables is None or t.name in tables:
            yield make(t)


# ---------------------------------------------------------------------------
# Netstock: the whole regenerated dataset, only when the sync has moved
# ---------------------------------------------------------------------------
@dlt.source(name="netstock")
def netstock_source(full_refresh: bool = False, tables: list[str] | None = None):
    spec = load_spec("netstock")
    sync = ns_client.sync_timestamp()

    def make(t: TableSpec):
        def fetch():
            state = dlt.current.resource_state()
            if not full_refresh and state.get("last_sync") == str(sync):
                return                      # nothing new: the sync has not run
            extracted_at = _now()
            yield from _stamp(ns_client.fetch(t.name), "S", extracted_at.isoformat(), extracted_at)
            state["last_sync"] = str(sync)
        return _resource(fetch, t)

    for t in spec.tables.values():
        if tables is None or t.name in tables:
            yield make(t)


# ---------------------------------------------------------------------------
# Azure cost export: append new days
# ---------------------------------------------------------------------------
@dlt.source(name="azure_cost")
def azure_cost_source(full_refresh: bool = False, tables: list[str] | None = None):
    spec = load_spec("azure_cost")
    t = spec.tables["focus_cost"]

    def fetch():
        state = dlt.current.resource_state()
        since = None if full_refresh else state.get("high_water")
        extracted_at = _now()
        rows = cost_client.rows_since(dt.date.fromisoformat(since) if since else None)
        if rows:
            state["high_water"] = max(r["ChargePeriodStart"] for r in rows).isoformat()
        yield from _stamp(rows, "I", extracted_at.isoformat(), extracted_at)

    yield _resource(fetch, t)


# ---------------------------------------------------------------------------
# Freight platform: carriers in full, shipments and invoices by updated-since
# ---------------------------------------------------------------------------
@dlt.source(name="freight")
def freight_source(full_refresh: bool = False, tables: list[str] | None = None):
    spec = load_spec("freight")
    lookback = dt.timedelta(days=spec.raw.get("lookback_days", 1))

    def make(t: TableSpec):
        def fetch():
            state = dlt.current.resource_state()
            extracted_at = _now()
            seq = extracted_at.isoformat()
            if t.strategy == "full_refresh":
                yield from _stamp(freight_client.list_rows(t.name), "S", seq, extracted_at)
                return
            high_water = None if full_refresh else state.get("high_water")
            since = (dt.date.fromisoformat(high_water) - lookback) if high_water else None
            rows = freight_client.list_rows(t.name, since)
            if rows:
                top = max(r[t.cursor] for r in rows)
                state["high_water"] = max(top.isoformat(), high_water or "")
            # Op S for the first load, so bronze_current starts from it; U after that.
            yield from _stamp(rows, "U" if high_water else "S", seq, extracted_at)
        return _resource(fetch, t)

    for t in spec.tables.values():
        if tables is None or t.name in tables:
            yield make(t)


BUILDERS = {
    "sage_x3": sage_x3_source,
    "hubspot": hubspot_source,
    "netstock": netstock_source,
    "azure_cost": azure_cost_source,
    "freight": freight_source,
}
