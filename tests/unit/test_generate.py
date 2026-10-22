"""The synthetic sources: deterministic, and consistent on every day."""
import datetime as dt

from sources import generate as g


def test_timeline_is_deterministic():
    a, b = g.build_timeline(), g.build_timeline()
    assert a.x3["SORDER"][:50] == b.x3["SORDER"][:50]
    assert a.hs["deal"][:50] == b.hs["deal"][:50]


def test_nothing_from_the_future_is_visible():
    tl = g.build_timeline()
    day = g.INITIAL_DATE
    s = g.state_as_of(tl, day)["sage_x3"]
    assert all(o["ORDDAT_0"] <= day for o in s["SORDER"])
    assert all(v["INVDAT_0"] <= day for v in s["SINVOICEV"])
    assert all(v["PAYDAT_0"] <= day or v["PAYDAT_0"] == g.NULL_DATE for v in s["SINVOICEV"])
    assert all(d["SHIDAT_0"] <= day for d in s["SDELIVERY"])
    assert all(d["DLVDAT_0"] <= day or d["DLVDAT_0"] == g.NULL_DATE for d in s["SDELIVERY"])
    orders = {o["SOHNUM_0"] for o in s["SORDER"]}
    assert {line["SOHNUM_0"] for line in s["SORDERQ"]} <= orders


def test_documents_reference_documents_that_exist():
    tl = g.build_timeline()
    s = g.state_as_of(tl, g.INITIAL_DATE)["sage_x3"]
    deliveries = {d["SDHNUM_0"] for d in s["SDELIVERY"]}
    assert {d["SDHNUM_0"] for d in s["SDELIVERYD"]} <= deliveries
    receipts = {r["PTHNUM_0"] for r in s["PRECEIPT"]}
    billed = {r["PTHNUM_0"] for r in s["PINVOICED"] if r["PTHNUM_0"]}
    assert billed <= receipts


def test_hard_deleted_orders_disappear():
    tl = g.build_timeline()
    deleted = [(soh, m["delete_on"]) for soh, m in tl.meta["order"].items() if m["delete_on"]]
    soh, on = deleted[0]
    before = {o["SOHNUM_0"] for o in g.state_as_of(tl, on - dt.timedelta(days=1))["sage_x3"]["SORDER"]}
    after = {o["SOHNUM_0"] for o in g.state_as_of(tl, on)["sage_x3"]["SORDER"]}
    assert soh in before and soh not in after


def test_truth_covers_every_hubspot_company():
    tl = g.build_timeline()
    hs = {c["id"] for c in tl.hs["company"]}
    truth = {t["source_key"] for t in tl.truth["customer_identity"] if t["source_system"] == "hubspot"}
    assert hs == truth
