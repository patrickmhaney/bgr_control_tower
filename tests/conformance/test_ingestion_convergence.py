"""Contract C2 conformance: bronze converges on the sources, deletes and gaps included.

Runs in its own temporary data directory, so it never touches your local
pipeline. It walks the clock through:

* a day-0 backfill, then daily incremental extracts that read only changes;
* a gap longer than CDC retention, which must trigger a fresh X3 snapshot
  rather than a silent hole;
* hard deletes in X3 (seen through CDC) and in HubSpot (seen through the key
  reconciliation);

and then requires bronze's current state to equal what each source shows -
every table, every column, every row. Any ingestion tool that replaces dlt
has to pass this test.
"""
import datetime as dt

import duckdb
import pytest

from ctl.__main__ import dbt
from ingestion.run import extract
from ingestion.verify import differences
from sources import clock
from sources import generate as g

pytestmark = [pytest.mark.pipeline, pytest.mark.isolated]


def _advance_to(day):
    days = (day - clock.status()["today"]).days
    if days > 0:
        clock.advance(days)


def test_bronze_converges_on_the_sources(isolated_data):
    clock.init()
    backfill = {s: sum(extract(s).values()) for s in ("sage_x3", "hubspot", "netstock", "azure_cost")}

    incremental = []
    for _ in range(3):                                    # daily incremental extracts
        clock.advance(1)
        incremental.append(sum(extract("sage_x3").values()))
        extract("hubspot")
    assert max(incremental) < backfill["sage_x3"] / 20

    clock.advance(clock.RETENTION_DAYS + 4)               # an outage longer than CDC retention
    extract("sage_x3")                                    # must resnapshot, not leave a hole
    extract("hubspot")

    _advance_to(dt.date(2026, 9, 17))                     # past a HubSpot hard delete
    extract("sage_x3")
    extract("hubspot", reconcile=True)
    while clock.status()["today"] < dt.date(2026, 10, 1):  # past two X3 hard deletes, daily-ish
        clock.advance(2)
        extract("sage_x3")
    for s in ("hubspot", "netstock", "azure_cost"):
        extract(s, reconcile=(s == "hubspot"))

    assert dbt("build", "--select", "path:models/bronze", "--quiet", check=False) == 0

    assert differences() == []

    con = duckdb.connect(str(isolated_data / "warehouse.duckdb"), read_only=True)
    con.execute("install delta; load delta")

    root = isolated_data / "bronze"
    snapshots = con.execute(f"select count(distinct _change_seq) from delta_scan('{root}/sage_x3/SORDER') "
                            "where _op = 'S'").fetchone()[0]
    assert snapshots >= 2, "the retention gap did not trigger a resnapshot"
    x3_deletes = con.execute(f"select count(*) from delta_scan('{root}/sage_x3/SORDER') "
                             "where _op = 'D'").fetchone()[0]
    assert x3_deletes >= 1, "no X3 hard delete arrived through CDC"
    hs_deletes = con.execute(f"select count(*) from delta_scan('{root}/hubspot/contact') "
                             "where _op = 'D'").fetchone()[0]
    assert hs_deletes >= 1, "the HubSpot key reconciliation missed a hard delete"
    assert clock.status()["today"] <= g.TIMELINE_END
