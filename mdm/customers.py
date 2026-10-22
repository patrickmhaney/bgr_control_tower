"""Customer matching: HubSpot companies to Sage X3 customers. There is no shared key.

Two providers, one output shape - a list of (hubspot company, X3 customer,
score, rule, ambiguous) - so swapping between them changes nothing downstream:

rules    v1's four deterministic probes, in descending precision. Most
         commercial MDM products match by rules, so this is the comparison
         that says what a rules engine would do with this data.
splink   Probabilistic record linkage (Splink on DuckDB). Weighs several
         imperfect signals together instead of trusting the first probe
         that fires.

Both are scored against the generator's ground truth by mdm/run.py.
"""
from __future__ import annotations

PROBES = [
    # rule,         score, condition
    ("exact_name",  0.95, "hs.name_upper = x3.name_upper"),
    ("alnum_name",  0.90, "hs.name_alnum = x3.name_alnum"),
    ("domain_stem", 0.75, "hs.domain is not null and hs.stem = x3.stem"),
    ("core_name",   0.60, "hs.name_core = x3.name_core"),
]


def _best_per_company(con, pairs_sql: str) -> list[dict]:
    """Keep each HubSpot company's strongest candidates; flag ties as ambiguous."""
    rows = con.execute(f"""
        with pairs as ({pairs_sql}),
        best_pair as (
            select hs_key, x3_key, max(score) as score, arg_max(rule, score) as rule
            from pairs group by hs_key, x3_key
        ),
        ranked as (
            select *, count(*) over (partition by hs_key, score) as tied,
                   rank() over (partition by hs_key order by score desc) as rnk
            from best_pair
        )
        select hs_key, min(x3_key) as x3_key, max(score) as score, min(rule) as rule,
               max(tied) > 1 as ambiguous
        from ranked where rnk = 1
        group by hs_key
    """).fetchall()
    return [dict(zip(["hs_key", "x3_key", "score", "rule", "ambiguous"], r)) for r in rows]


def match_rules(con) -> list[dict]:
    union = "\nunion all\n".join(
        f"select hs.source_key as hs_key, x3.source_key as x3_key, '{rule}' as rule, "
        f"{score} as score from customer_records hs join customer_records x3 on {cond} "
        f"where hs.source_system = 'hubspot' and x3.source_system = 'sage_x3'"
        for rule, score, cond in PROBES)
    return _best_per_company(con, union)


def match_splink(con, threshold: float = 0.5) -> list[dict]:
    import splink.comparison_library as cl
    from splink import Linker, SettingsCreator, block_on
    from splink.backends.duckdb import DuckDBAPI

    con.execute("""create or replace temp table mdm_x3 as
                   select uid, name_alnum, name_core, stem, country, source_key
                   from customer_records where source_system = 'sage_x3'""")
    con.execute("""create or replace temp table mdm_hs as
                   select uid, name_alnum, name_core, stem, country, source_key
                   from customer_records where source_system = 'hubspot'""")
    db_api = DuckDBAPI(connection=con)
    left = db_api.register("mdm_x3", dataset_display_name="sage_x3")
    right = db_api.register("mdm_hs", dataset_display_name="hubspot")
    settings = SettingsCreator(
        link_type="link_only",
        unique_id_column_name="uid",
        comparisons=[
            cl.JaroWinklerAtThresholds("name_core", [0.97, 0.9]),
            cl.ExactMatch("name_alnum"),
            cl.ExactMatch("stem"),
            cl.ExactMatch("country"),
        ],
        blocking_rules_to_generate_predictions=[
            block_on("substr(name_core, 1, 4)"),
            block_on("stem"),
        ],
        retain_intermediate_calculation_columns=False,
    )
    linker = Linker([left, right], settings, log_level=40)
    linker.training.estimate_probability_two_random_records_match(
        [block_on("name_alnum")], recall=0.7)
    linker.training.estimate_u_using_random_sampling(max_pairs=200_000, seed=7)
    linker.training.estimate_parameters_using_expectation_maximisation(
        block_on("substr(name_core, 1, 4)"))
    linker.training.estimate_parameters_using_expectation_maximisation(block_on("stem"))
    predictions = linker.inference.predict(threshold_match_probability=threshold)
    con.execute(f"create or replace temp table mdm_predictions as select * from {predictions.physical_name}")
    return _best_per_company(con, """
        select case when uid_l like 'hubspot:%' then substr(uid_l, 9) else substr(uid_r, 9) end as hs_key,
               case when uid_l like 'sage_x3:%' then substr(uid_l, 9) else substr(uid_r, 9) end as x3_key,
               'splink' as rule, round(match_probability, 4) as score
        from mdm_predictions
    """)
