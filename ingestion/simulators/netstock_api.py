"""Netstock, read as a snapshot API.

PRODUCTION SWAP
---------------
Replace `fetch()` with the real endpoint. The rest of the design - replace
disposition, no cursor, freshness carried through - is correct regardless of
what the API turns out to look like.

WHY A SNAPSHOT AND NOT AN INCREMENTAL
-------------------------------------
Netstock regenerates its planning dataset wholesale on each sync and stamps
every row with the same `last_sync_at`. There is no per-row change signal
because there is no per-row change - the whole set is recomputed. An
incremental read would therefore be wrong, not merely inefficient: a row that
drops out of the recomputed set (an item no longer planned at a location) would
persist in the warehouse forever.

`sync_timestamp()` is exposed separately so freshness reaches the mart. This
source is stale relative to the ERP by construction, and hiding that is how a
planner ends up reconciling two numbers that were never as of the same moment.

SCHEDULE RISK
-------------
The API is unconfirmed. Netstock's integration surface is built to sync with an
ERP, not to serve a warehouse. Get a sample extract during discovery.
"""
from __future__ import annotations

import datetime as dt

from . import _mock_db

SCHEMA = "netstock"


def sync_timestamp() -> dt.date | None:
    rows = _mock_db.rows(f'select max(last_sync_at) as ts from {SCHEMA}."item_location"')
    return rows[0]["ts"] if rows else None


def fetch(dataset: str) -> list[dict]:
    """One call, the whole dataset. No paging, no cursor, no filter."""
    return _mock_db.rows(f'select * from {SCHEMA}."{dataset}"')
