"""Pangea, read as a REST API with nested children.

PRODUCTION SWAP
---------------
Replace `list_shipments()` and `children_for()` with real endpoints. The
lookback behaviour and the bulk-child read are the parts to preserve.

TWO THINGS THIS SHAPE IS TEACHING
---------------------------------
1. **A strict high-water mark loses data here.** Charges post late and delivery
   events arrive days after a shipment is created, so a cursor that only ever
   collects *new* shipments will permanently under-report cost and never see a
   delivery. Shipments are therefore re-read over a lookback window rather than
   collected once. The metric this protects is Cost Per Shipment, where the
   header already disagrees with the charge lines by 9.9%.

2. **Children must be fetched in bulk, not per parent.** `children_for()` takes
   a list of shipment ids and issues one call. Fetching charges one shipment at
   a time is an N+1 that is invisible at POC scale and fatal on a backfill -
   3,509 shipments becomes 10,527 API calls across three child types. If the
   real API has no bulk or date-ranged child endpoint, that constraint needs to
   be found during discovery, because it changes the backfill plan.

SCHEDULE RISK
-------------
The product is still unidentified. Two of the four buildable metrics sit
entirely on this source.
"""
from __future__ import annotations

import datetime as dt

from . import _mock_db

SCHEMA = "pangea"
PAGE_SIZE = 500
CHILD_BATCH = 500


class PangeaClient:
    def __init__(self):
        self.requests_made = 0

    def list_shipments(self, created_since: dt.date | None = None):
        after = 0
        while True:
            self.requests_made += 1
            where, params = "", []
            if created_since is not None:
                where, params = "where created_at >= ?", [created_since]
            page = _mock_db.rows(
                f'select * from {SCHEMA}."shipment" {where} '
                f"order by shipment_id limit ? offset ?",
                params + [PAGE_SIZE, after],
            )
            if not page:
                return
            yield from page
            if len(page) < PAGE_SIZE:
                return
            after += PAGE_SIZE

    def children_for(self, child: str, shipment_ids: list[str]) -> list[dict]:
        """One call per batch of parents, not one call per parent."""
        out = []
        for start in range(0, len(shipment_ids), CHILD_BATCH):
            batch = shipment_ids[start:start + CHILD_BATCH]
            self.requests_made += 1
            placeholders = ", ".join("?" for _ in batch)
            out.extend(_mock_db.rows(
                f'select * from {SCHEMA}."{child}" '
                f"where shipment_id in ({placeholders})",
                list(batch),
            ))
        return out

    def fetch(self, table: str) -> list[dict]:
        self.requests_made += 1
        return _mock_db.rows(f'select * from {SCHEMA}."{table}"')
