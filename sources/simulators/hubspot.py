"""HubSpot, read as a paginated REST API.

PRODUCTION SWAP
---------------
Replace `_page()` with a call to `https://api.hubapi.com/crm/v3/objects/<object>`
carrying a private-app bearer token, and map `after` / `paging.next.after`
onto the cursor. Replace `list_ids()` with the same endpoint asking for the
`hs_object_id` property only. Everything above `_page()` - pagination,
the archived second pass, the modified-since filter, the request budget -
is real and stays.

Reproduced on purpose:

* Pagination, so a backfill's cost shows as a request count.
* The archived second pass. HubSpot omits archived records unless asked, and
  they arrive flagged, not deleted.
* A stable total order. Offset pagination over a non-unique key silently
  loses and duplicates rows with an identical row count - it happened in v1
  of this project and only a dbt grain test caught it. Always page by the
  primary key.
* Hard deletes. A deleted contact simply stops appearing, which only a key
  reconciliation notices.
"""
from __future__ import annotations

import datetime as dt

import duckdb

from core.settings import settings

SCHEMA = "hubspot"
PAGE_SIZE = 100
RATE_LIMIT_REQUESTS = 5000


class RateLimitExceeded(RuntimeError):
    pass


class HubSpotClient:
    def __init__(self, page_size: int = PAGE_SIZE):
        self.page_size = page_size
        self.requests_made = 0

    def _query(self, sql: str, params: list) -> list[dict]:
        con = duckdb.connect(settings.mock_db, read_only=True)
        try:
            cur = con.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            con.close()

    def _page(self, obj: str, props: list[str], where: str, params: list,
              after: int, order_by: list[str]) -> list[dict]:
        self.requests_made += 1
        if self.requests_made > RATE_LIMIT_REQUESTS:
            raise RateLimitExceeded("Request budget exceeded. In production this is a 429: back off.")
        cols = ", ".join(f'"{c}"' for c in props)
        order = ", ".join(f'"{c}"' for c in order_by)
        return self._query(f'select {cols} from {SCHEMA}."{obj}" {where} '
                           f"order by {order} limit ? offset ?",
                           params + [self.page_size, after])

    def properties(self, obj: str) -> list[str]:
        """The property schema. Re-read every run: admins add and rename properties."""
        return [r["column_name"] for r in self._query(
            "select column_name from duckdb_columns() where schema_name = ? and table_name = ? "
            "order by column_index", [SCHEMA, obj])]

    def list_objects(self, obj: str, order_by: list[str], modified_since: dt.date | None = None,
                     cursor: str | None = None, include_archived: bool = True):
        props = self.properties(obj)
        if not order_by or any(c not in props for c in order_by):
            raise ValueError(f"{obj}: order_by must be existing, unique key columns")
        passes = [False, True] if ("archived" in props and include_archived) else [None]
        for archived in passes:
            clauses, params = [], []
            if archived is not None:
                clauses.append('"archived" = ?')
                params.append(archived)
            if modified_since is not None and cursor in props:
                clauses.append(f'"{cursor}" >= ?')
                params.append(modified_since)
            where = ("where " + " and ".join(clauses)) if clauses else ""
            after = 0
            while True:
                page = self._page(obj, props, where, params, after, order_by)
                yield from page
                if len(page) < self.page_size:
                    break
                after += self.page_size

    def list_ids(self, obj: str, key: str = "id") -> set[str]:
        """Every live id, archived included, for a key reconciliation."""
        self.requests_made += 1
        return {r[key] for r in self._query(f'select "{key}" from {SCHEMA}."{obj}"', [])}
