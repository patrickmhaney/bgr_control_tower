"""Paycom, read as scheduled report exports landing on SFTP.

PRODUCTION SWAP
---------------
Replace `deliver_reports()` with nothing - Paycom's Report Center writes the
files. Replace `list_files()`/`read_file()` with paramiko or an SFTP mount
against the real drop directory. The freshness assertion, the header-driven
parse and the everything-is-a-string contract all stay.

WHY THIS SHAPE
--------------
Paycom has no queryable backend and an API too thin to drive reporting, so the
real integration is: an admin configures a saved report, schedules it, and
Paycom drops a delimited file. That means:

* **Full refresh, always.** There is no change signal of any kind.
* **A missing file is invisible.** A report that silently stops arriving looks
  exactly like a report with no changes, so freshness is asserted rather than
  assumed - `read_file` raises if the newest file is older than the cadence.
* **Read by header, never by position.** Anyone with report-builder access can
  reorder or add a column, and it will not be announced.
* **Nothing is cast here.** Dates stay `MM/DD/YYYY` and amounts stay strings so
  the landing layer records what actually arrived. Casting is staging's job,
  and doing it in the extractor destroys the evidence when a value fails.
"""
from __future__ import annotations

import csv
import datetime as dt
import os

from . import _mock_db

SCHEMA = "paycom"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DROP_DIR = os.path.join(ROOT, "landing", "_incoming", "paycom")

#: Reports are scheduled daily. Anything older than this is a failed delivery.
MAX_FILE_AGE_DAYS = 2


class StaleExportError(RuntimeError):
    pass


def deliver_reports(as_of: dt.date | None = None) -> list[str]:
    """SIMULATION ONLY. Stands in for Paycom writing files to the SFTP drop."""
    as_of = as_of or dt.date.today()
    os.makedirs(DROP_DIR, exist_ok=True)
    written = []
    for (table,) in [
        (t,) for t in ("employee", "check", "earning_detail",
                       "deduction_detail", "tax_detail", "gl_mapping")
    ]:
        rows = _mock_db.rows(f'select * from {SCHEMA}."{table}"')
        path = os.path.join(DROP_DIR, f"{table.upper()}_{as_of:%Y%m%d}.csv")
        with open(path, "w", newline="") as fh:
            if rows:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
                writer.writeheader()
                for row in rows:
                    writer.writerow({k: "" if v is None else str(v) for k, v in row.items()})
        written.append(path)
    return written


def list_files(table: str) -> list[str]:
    if not os.path.isdir(DROP_DIR):
        return []
    prefix = f"{table.upper()}_"
    return sorted(
        os.path.join(DROP_DIR, f)
        for f in os.listdir(DROP_DIR)
        if f.startswith(prefix) and f.endswith(".csv")
    )


def read_latest(table: str, as_of: dt.date | None = None) -> list[dict]:
    """Read the newest export for a table, refusing a stale one.

    The freshness check is the whole safety net for this source. Without it a
    broken schedule produces a warehouse that quietly serves last month's
    payroll as if it were current.
    """
    files = list_files(table)
    if not files:
        raise StaleExportError(
            f"no {table.upper()}_*.csv in {DROP_DIR}. In production this means the "
            f"scheduled report did not arrive - page someone, do not carry on."
        )
    newest = files[-1]
    stamp = dt.datetime.strptime(os.path.basename(newest).rsplit("_", 1)[1][:8], "%Y%m%d").date()
    age = ((as_of or dt.date.today()) - stamp).days
    if age > MAX_FILE_AGE_DAYS:
        raise StaleExportError(
            f"{os.path.basename(newest)} is {age} days old (limit {MAX_FILE_AGE_DAYS}). "
            f"A stale export is indistinguishable from an unchanged one, so this "
            f"fails rather than loading it."
        )
    with open(newest, newline="") as fh:
        # Header-driven, so a reordered or added column does not shift values.
        return [{k: (v if v != "" else None) for k, v in row.items()}
                for row in csv.DictReader(fh)]
