"""Contract C3 conformance: any MDM provider's output must pass this."""
import duckdb
import pytest

from core.settings import settings
from mdm.run import score_against_truth, validate

pytestmark = pytest.mark.pipeline


def _tables():
    con = duckdb.connect()
    con.execute("install delta; load delta")
    out = {}
    for name in ("mdm_xref", "mdm_golden_customer", "mdm_golden_employee"):
        cur = con.execute(f"select * from delta_scan('{settings.bronze_root}/mdm/{name}')")
        cols = [d[0] for d in cur.description]
        out[name] = [dict(zip(cols, r)) for r in cur.fetchall()]
    return out


def test_output_matches_contract():
    validate(_tables())


def test_every_source_record_has_a_golden_record():
    t = _tables()
    golden = {g["golden_key"] for g in t["mdm_golden_customer"]} | {
        g["golden_key"] for g in t["mdm_golden_employee"]}
    assert {x["golden_key"] for x in t["mdm_xref"]} <= golden


def test_customer_matching_quality_floor():
    score = score_against_truth(_tables()["mdm_xref"])
    assert score is not None
    assert score["precision"] >= 0.8 and score["recall"] >= 0.8, score
