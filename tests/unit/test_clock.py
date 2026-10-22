"""The clock writes SQL Server-shaped change data capture rows."""
import duckdb

from sources import clock


def test_advance_captures_inserts_and_paired_updates(isolated_data):
    clock.init()
    clock.advance(3)                              # the first day is a Sunday: no new orders
    con = duckdb.connect(str(isolated_data / "mock_sources.duckdb"), read_only=True)
    ops = dict(con.execute('select "__$operation", count(*) from cdc."dbo_SORDER_CT" group by 1').fetchall())
    assert ops.get(2, 0) > 0                      # new orders
    assert ops.get(3, 0) == ops.get(4, 0) > 0     # every update has before and after images
    rows = con.execute('select "__$seqval", "__$operation", "SOHNUM_0" from cdc."dbo_SORDER_CT" '
                       'where "__$operation" in (3, 4) order by "__$start_lsn", "__$seqval"').fetchall()
    for before, after in zip(rows[::2], rows[1::2], strict=True):
        assert (before[1], after[1]) == (3, 4) and before[2] == after[2]


def test_cleanup_purges_beyond_retention(isolated_data):
    clock.init()
    clock.advance(clock.RETENTION_DAYS + 2)
    status = clock.status()
    assert status["low_water_lsn"] > 1            # the oldest change rows are gone
