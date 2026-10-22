"""The source records MDM matches, read from silver staging in the warehouse.

Names are normalised here once, identically for both sides of every match. A
subtle difference between the two sides of a join is the classic way entity
resolution quietly loses rows.
"""
from __future__ import annotations

import duckdb

from core.settings import settings


def connect() -> duckdb.DuckDBPyConnection:
    """An in-memory workspace with the warehouse attached read-only.

    MDM never writes to the warehouse: its output is contract C3 in raw
    storage, like an external product's. Splink needs somewhere writable for
    its working tables, which is the in-memory database.
    """
    con = duckdb.connect()
    con.execute(f"attach '{settings.warehouse_path}' as warehouse (read_only)")
    return con


def legal_suffix_pattern(con) -> str:
    suffixes = [r[0] for r in con.execute(
        "select suffix from warehouse.seed.legal_suffix order by length(suffix) desc, suffix").fetchall()]
    return "|".join(suffixes) or "INC|LLC|LTD|CORP|CO|GROUP"


def customer_records(con) -> str:
    """Create temp table `customer_records`: one row per X3 customer and HubSpot company."""
    pattern = legal_suffix_pattern(con)
    con.execute(f"""
        create or replace temp table customer_records as
        with raw as (
            select 'sage_x3' as source_system, customer_code as source_key,
                   customer_name as name, null::varchar as domain,
                   case when currency_code = 'CAD' then 'CA' else 'US' end as country,
                   customer_code as x3_code
            from warehouse.silver.stg_sage_x3__bpcustomer
            union all
            select 'hubspot', company_id, company_name, domain,
                   case when country = 'Canada' then 'CA' else 'US' end, null
            from warehouse.silver.stg_hubspot__company
        )
        select
            source_system || ':' || source_key as uid,
            source_system, source_key, name, domain, country, x3_code,
            upper(trim(name)) as name_upper,
            upper(regexp_replace(name, '[^a-zA-Z0-9]', '', 'g')) as name_alnum,
            trim(regexp_replace(upper(regexp_replace(name, '[^a-zA-Z0-9 ]', '', 'g')),
                                '\\s+({pattern})$', '')) as name_core,
            lower(left(regexp_replace(coalesce(split_part(domain, '.', 1), name),
                                      '[^a-zA-Z0-9]', '', 'g'), 18)) as stem
        from raw
    """)
    return "customer_records"
