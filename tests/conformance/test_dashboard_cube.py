"""The dashboard cube: one row per grain, consistent ratios, and the golden answers through it."""
import duckdb
import pytest

from core.settings import settings

pytestmark = pytest.mark.pipeline


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(settings.warehouse_path, read_only=True)
    yield c
    c.close()


def test_one_row_per_cube_and_grain(con):
    # What the fixed-metric guard (COUNTROWS = 1) relies on.
    from serving.powerbi import Cube

    for name, c in Cube().cubes.items():
        keys = ", ".join(f'"{d}"' for d in c["dims"]) or "1"
        dupes = con.execute(f"select count(*) from (select {keys} from marts.dashboard_cube "
                            f"where _cube = ? group by {keys} having count(*) > 1)", [name]).fetchone()[0]
        assert dupes == 0, name


def test_stored_ratios_match_their_components(con):
    from serving.powerbi import Cube

    cube = Cube()
    for m in cube.columns:
        r = cube.rollups[m]
        if r["kind"] != "ratio":
            continue
        bad = con.execute(f'select count(*) from marts.dashboard_cube where "{r["denominator"]}" <> 0 '
                          f'and abs("{m}" - "{r["numerator"]}" / "{r["denominator"]}") > 1e-9').fetchone()[0]
        assert bad == 0, m


def test_golden_answers_through_the_cube():
    from serving.powerbi_parity import local

    assert local() == []
