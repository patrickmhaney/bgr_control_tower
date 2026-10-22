"""Employee matching: X3 users, X3 sales reps and HubSpot owners describe the same people.

Deterministic, and shared by both providers: the signals here are exact or
nearly so, which is where rules beat a probabilistic model.

    X3 user (AUTILIS)   the anchor: every person who creates documents
    HubSpot owner       matched on lower-cased email (0.99), then on name (0.80)
    X3 rep (REPRESENT)  matched on name: REPNAM_0 is "LAST FIRST", upper case (0.85)

Two X3 users have no email recorded, so their HubSpot owners fall through to
the name match - which is the point of having a second probe.
"""
from __future__ import annotations


def match_employees(con) -> list[dict]:
    """Rows of (source_system, source_key, golden_key, score, rule, status)."""
    con.execute("""
        create or replace temp table emp_users as
        select user_code, user_name, email,
               upper(trim(split_part(user_name, ' ', 2)) || ' ' || trim(split_part(user_name, ' ', 1)))
                   as last_first
        from warehouse.silver.stg_sage_x3__autilis
        where function_profile <> 'SYSTEM'
    """)
    rows = []
    for user_code, in con.execute("select user_code from emp_users order by user_code").fetchall():
        rows.append(("sage_x3.AUTILIS", user_code, f"E-{user_code}", 1.0, "anchor", "anchor"))

    owners = con.execute("""
        select o.owner_id,
               coalesce(by_email.user_code, by_name.user_code) as user_code,
               case when by_email.user_code is not null then 0.99
                    when by_name.user_code is not null then 0.80 end as score,
               case when by_email.user_code is not null then 'email'
                    when by_name.user_code is not null then 'name' end as rule
        from warehouse.silver.stg_hubspot__owner o
        left join emp_users by_email on by_email.email = o.email
        left join emp_users by_name
            on by_name.last_first = upper(o.last_name || ' ' || o.first_name)
        order by o.owner_id
    """).fetchall()
    for owner_id, user_code, score, rule in owners:
        if user_code:
            rows.append(("hubspot", owner_id, f"E-{user_code}", score, rule,
                         "auto" if score >= 0.85 else "needs_review"))
        else:
            rows.append(("hubspot", owner_id, f"E-HS-{owner_id}", None, None, "unmatched"))

    reps = con.execute("""
        select r.rep_code, u.user_code
        from warehouse.silver.stg_sage_x3__represent r
        left join emp_users u on u.last_first = upper(r.rep_name)
        order by r.rep_code
    """).fetchall()
    for rep_code, user_code in reps:
        if user_code:
            rows.append(("sage_x3.REPRESENT", rep_code, f"E-{user_code}", 0.85, "name", "auto"))
        else:
            rows.append(("sage_x3.REPRESENT", rep_code, f"E-REP-{rep_code}", None, None, "unmatched"))
    return [dict(zip(["source_system", "source_key", "golden_key", "match_score", "match_rule",
                      "steward_status"], r)) for r in rows]
