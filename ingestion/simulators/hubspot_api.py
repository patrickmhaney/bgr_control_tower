"""HubSpot, read as a paginated REST API.

PRODUCTION SWAP
---------------
Replace `_page()` with an HTTP call to
`https://api.hubapi.com/crm/v3/objects/<object>` carrying a private-app bearer
token, and map `after`/`paging.next.after` onto the cursor. The pagination
loop, the archived second pass, the modified-since filter and the rate-limit
accounting above it are all real and stay.

WHAT IS REPRODUCED, AND WHY IT MATTERS
--------------------------------------
* **Pagination.** Callers get pages, never a whole table, so backfill cost is
  visible as a request count rather than hidden in a single query.
* **The archived second pass.** HubSpot does not return archived records unless
  asked. Forgetting costs 12 companies, 23 contacts and 11 deals here - and
  they arrive as `archived = true`, not as deletions, so the mart decides what
  to do with them, never the extractor.
* **Rate limiting.** Requests are counted and the caller can read the total.
  A real backfill has to pace against a per-token limit and back off on 429.
* **Property selection.** HubSpot returns nothing but a handful of defaults
  unless properties are named. The list is passed explicitly for the same
  reason the ERP enumerates columns: an unnamed property is silently absent,
  which looks identical to a null.
* **A stable total order.** Offset pagination over a non-unique sort key
  silently loses and duplicates rows, because the database is free to return
  ties in a different order on each page request. This is not hypothetical:
  the first version of this module paged `deal_stage_history` ordered by
  `deal_id`, which has 850 distinct values across 3,606 rows, and lost 26 rows
  while duplicating 26 others. **The row count was identical**, so a
  count-based reconciliation passed - only the grain test in dbt caught it.
  Pagination therefore orders by the primary key, and any real extractor must
  do the same or use keyset/cursor pagination (which is what HubSpot's `after`
  token actually is).
"""
from __future__ import annotations

import datetime as dt

from . import _mock_db

SCHEMA = "hubspot"
PAGE_SIZE = 100

#: Simulated per-run request budget, so a runaway backfill is caught in the POC
#: rather than as a 429 storm in production.
RATE_LIMIT_REQUESTS = 5000


class RateLimitExceeded(RuntimeError):
    pass


class HubSpotClient:
    def __init__(self, page_size: int = PAGE_SIZE):
        self.page_size = page_size
        self.requests_made = 0

    # -- transport -------------------------------------------------------
    def _page(self, object_type: str, properties: list[str], where: str,
              params: list, after: int, order_by: list[str]) -> list[dict]:
        self.requests_made += 1
        if self.requests_made > RATE_LIMIT_REQUESTS:
            raise RateLimitExceeded(
                f"exceeded {RATE_LIMIT_REQUESTS} requests. In production this is "
                f"a 429 with a Retry-After header; back off, do not fail the run."
            )
        cols = ", ".join(f'"{c}"' for c in properties)
        order = ", ".join(f'"{c}"' for c in order_by)
        return _mock_db.rows(
            f'select {cols} from {SCHEMA}."{object_type}" '
            f"{where} order by {order} limit ? offset ?",
            params + [self.page_size, after],
        )

    # -- schema ----------------------------------------------------------
    def properties(self, object_type: str) -> list[str]:
        """The property schema. Re-read every run - HubSpot lets an admin add
        or rename a property at any time, and neither event notifies you."""
        return [
            r["column_name"]
            for r in _mock_db.rows(
                "select column_name from duckdb_columns() "
                "where schema_name = ? and table_name = ? order by column_index",
                [SCHEMA, object_type],
            )
        ]

    # -- reads -----------------------------------------------------------
    def list_objects(self, object_type: str, modified_since: dt.date | None = None,
                     cursor_column: str | None = None, include_archived: bool = True,
                     order_by: list[str] | None = None):
        """Yield every record, paging until exhausted.

        Two passes when the object supports archiving: the default pass returns
        live records, the second returns archived ones. That is HubSpot's
        actual behaviour and it is the single easiest thing to get wrong.

        `order_by` must be a unique key. Passing a non-unique one silently
        loses and duplicates rows - see the module docstring.
        """
        properties = self.properties(object_type)
        if not order_by:
            raise ValueError(
                f"{object_type}: order_by is required and must be unique. "
                f"Offset pagination over a non-unique order silently loses rows."
            )
        missing = [c for c in order_by if c not in properties]
        if missing:
            raise ValueError(f"{object_type}: order_by columns {missing} do not exist")
        has_archived = "archived" in properties

        passes = [False]
        if has_archived and include_archived:
            passes.append(True)

        for archived in passes:
            clauses, params = [], []
            if has_archived:
                clauses.append('"archived" = ?')
                params.append(archived)
            if modified_since is not None and cursor_column in properties:
                clauses.append(f'"{cursor_column}" >= ?')
                params.append(modified_since)
            where = ("where " + " and ".join(clauses)) if clauses else ""

            after = 0
            while True:
                page = self._page(object_type, properties, where, params, after, order_by)
                if not page:
                    break
                yield from page
                if len(page) < self.page_size:
                    break
                after += self.page_size
