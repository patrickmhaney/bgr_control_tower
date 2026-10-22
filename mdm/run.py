"""Run the selected MDM provider and land contract C3 in raw storage.

    python -m mdm.run                      # the provider in config (MDM_PROVIDER)
    python -m mdm.run --provider rules     # swap drill 1: nothing downstream changes

Reads silver staging, matches, validates the output against mdm/contract.yml,
writes the three C3 tables as Delta under <bronze_root>/mdm/, and - when the
synthetic sources' answer key is available - scores customer matching for
precision and recall. The score is written to <data_dir>/mdm_quality.json and
published as a governance metric through gold.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os

import pyarrow as pa
import yaml

from core import storage
from core.settings import settings

from . import customers, employees, inputs

HERE = os.path.dirname(os.path.abspath(__file__))
CONTRACT = os.path.join(HERE, "contract.yml")


def _customer_tables(con, matches: list[dict], today: dt.date):
    x3 = con.execute("select source_key, name from customer_records "
                     "where source_system = 'sage_x3' order by source_key").fetchall()
    hs = con.execute("select source_key, name from customer_records "
                     "where source_system = 'hubspot' order by source_key").fetchall()
    by_hs = {m["hs_key"]: m for m in matches}
    xref, golden = [], {}
    for code, name in x3:
        key = f"C-{code}"
        xref.append({"domain": "customer", "source_system": "sage_x3", "source_key": code,
                     "golden_key": key, "match_score": 1.0, "match_rule": "anchor",
                     "steward_status": "anchor", "valid_from": today})
        golden[key] = {"golden_key": key, "golden_name": name, "x3_customer_code": code,
                       "hubspot_company_id": None, "source_scope": "erp_only"}
    for company_id, name in hs:
        m = by_hs.get(company_id)
        if m:
            key = f"C-{m['x3_key']}"
            status = "needs_review" if m["ambiguous"] or m["score"] < 0.75 else "auto"
            xref.append({"domain": "customer", "source_system": "hubspot",
                         "source_key": company_id, "golden_key": key,
                         "match_score": float(m["score"]), "match_rule": m["rule"],
                         "steward_status": status, "valid_from": today})
            g = golden[key]
            g["source_scope"] = "both"
            g["hubspot_company_id"] = min(filter(None, [g["hubspot_company_id"], company_id]))
        else:
            key = f"C-HS-{company_id}"
            xref.append({"domain": "customer", "source_system": "hubspot",
                         "source_key": company_id, "golden_key": key, "match_score": None,
                         "match_rule": None, "steward_status": "unmatched", "valid_from": today})
            golden[key] = {"golden_key": key, "golden_name": name, "x3_customer_code": None,
                           "hubspot_company_id": company_id, "source_scope": "crm_only"}
    return xref, list(golden.values())


def _employee_tables(con, rows: list[dict], today: dt.date):
    people = {r[0]: r for r in con.execute(
        "select user_code, user_name, email from warehouse.silver.stg_sage_x3__autilis").fetchall()}
    owners = {r[0]: r for r in con.execute(
        "select owner_id, first_name || ' ' || last_name, email from warehouse.silver.stg_hubspot__owner"
    ).fetchall()}
    reps = {r[0]: r[1] for r in con.execute(
        "select rep_code, rep_name from warehouse.silver.stg_sage_x3__represent").fetchall()}
    xref, golden = [], {}
    for r in rows:
        score = None if r["match_score"] is None else float(r["match_score"])
        xref.append({"domain": "employee", **r, "match_score": score, "valid_from": today})
        key, system, src = r["golden_key"], r["source_system"], r["source_key"]
        g = golden.setdefault(key, {"golden_key": key, "display_name": None, "email": None,
                                    "x3_user_code": None, "x3_rep_code": None,
                                    "hubspot_owner_id": None})
        if system == "sage_x3.AUTILIS":
            g["x3_user_code"], g["display_name"] = src, people[src][1]
            g["email"] = people[src][2] or g["email"]
        elif system == "hubspot":
            g["hubspot_owner_id"] = src
            g["display_name"] = g["display_name"] or owners[src][1]
            g["email"] = g["email"] or owners[src][2]
        else:
            g["x3_rep_code"] = src
            g["display_name"] = g["display_name"] or reps[src].title()
    return xref, list(golden.values())


def validate(tables: dict[str, list[dict]]) -> None:
    """Fail loudly if the provider's output breaks contract C3."""
    with open(CONTRACT) as fh:
        contract = yaml.safe_load(fh)["tables"]
    for name, spec in contract.items():
        rows = tables[name]
        for col, c in spec["columns"].items():
            for row in rows:
                v = row.get(col)
                if c.get("required") and v in (None, ""):
                    raise ValueError(f"C3 violation: {name}.{col} is required")
                if v is not None and "values" in c and v not in c["values"]:
                    raise ValueError(f"C3 violation: {name}.{col} has {v!r}")
        keys = [tuple(r[k] for k in spec["unique"]) for r in rows]
        if len(keys) != len(set(keys)):
            raise ValueError(f"C3 violation: {name} is not unique on {spec['unique']}")


def score_against_truth(xref: list[dict]) -> dict | None:
    """Pairwise precision and recall of HubSpot-to-X3 customer links, if truth exists."""
    import duckdb

    if not os.path.exists(settings.mock_db):
        return None
    con = duckdb.connect(settings.mock_db, read_only=True)
    try:
        truth = con.execute("select source_key, entity_id from truth.customer_identity "
                            "where source_system = 'hubspot' and entity_id not like 'HS-%'"
                            ).fetchall()
    except duckdb.CatalogException:
        return None
    finally:
        con.close()
    true_links = {(k, e) for k, e in truth}
    predicted = {(r["source_key"], r["golden_key"][2:]) for r in xref
                 if r["domain"] == "customer" and r["source_system"] == "hubspot"
                 and not r["golden_key"].startswith("C-HS-")}
    tp = len(true_links & predicted)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(true_links) if true_links else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"true_links": len(true_links), "predicted_links": len(predicted),
            "correct_links": tp, "precision": round(precision, 4),
            "recall": round(recall, 4), "f1": round(f1, 4)}


def run_mdm(provider: str | None = None) -> dict:
    provider = provider or settings.mdm_provider
    today = dt.date.today()
    con = inputs.connect()
    try:
        inputs.customer_records(con)
        matches = customers.match_splink(con) if provider == "splink" else customers.match_rules(con)
        cust_xref, cust_golden = _customer_tables(con, matches, today)
        emp_xref, emp_golden = _employee_tables(con, employees.match_employees(con), today)
    finally:
        con.close()
    tables = {"mdm_xref": cust_xref + emp_xref,
              "mdm_golden_customer": cust_golden,
              "mdm_golden_employee": emp_golden}
    validate(tables)
    schemas = {
        "mdm_xref": pa.schema([("domain", pa.string()), ("source_system", pa.string()),
                               ("source_key", pa.string()), ("golden_key", pa.string()),
                               ("match_score", pa.float64()), ("match_rule", pa.string()),
                               ("steward_status", pa.string()), ("valid_from", pa.date32())]),
        "mdm_golden_customer": pa.schema([(c, pa.string()) for c in
                                          ("golden_key", "golden_name", "x3_customer_code",
                                           "hubspot_company_id", "source_scope")]),
        "mdm_golden_employee": pa.schema([(c, pa.string()) for c in
                                          ("golden_key", "display_name", "email", "x3_user_code",
                                           "x3_rep_code", "hubspot_owner_id")]),
    }
    for name, rows in tables.items():
        storage.write_delta(storage.join(settings.bronze_root, "mdm", name),
                            pa.Table.from_pylist(rows, schema=schemas[name]))
    quality = {"provider": provider, "run_date": today.isoformat(),
               "customer": score_against_truth(cust_xref),
               "customer_links": sum(1 for r in cust_xref if r["source_system"] == "hubspot"
                                     and r["steward_status"] != "unmatched"),
               "needs_review": sum(1 for r in tables["mdm_xref"]
                                   if r["steward_status"] == "needs_review")}
    os.makedirs(settings.data_dir, exist_ok=True)
    with open(os.path.join(settings.data_dir, "mdm_quality.json"), "w") as fh:
        json.dump(quality, fh, indent=2)
    c = quality["customer"] or {}
    print(f"mdm {provider:<7} customer links {quality['customer_links']}, "
          f"needs review {quality['needs_review']}"
          + (f", precision {c['precision']:.3f}, recall {c['recall']:.3f}" if c else ""))
    return quality


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m mdm.run")
    p.add_argument("--provider", choices=["splink", "rules"])
    run_mdm(p.parse_args().provider)


if __name__ == "__main__":
    main()
