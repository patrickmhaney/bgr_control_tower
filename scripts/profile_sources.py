"""Reproduce every number quoted in docs/metric_feasibility.md.

    python scripts/profile_sources.py            # all sections
    python scripts/profile_sources.py otd cost   # named sections

Read-only against mock_sources.duckdb. No dbt required - this is the
feasibility audit and it deliberately runs before any model exists.
"""
import sys
import duckdb

DB = "mock_sources.duckdb"

SECTIONS = {}


def section(name):
    def deco(fn):
        SECTIONS[name] = fn
        return fn
    return deco


def show(con, label, sql):
    print(f"\n--- {label}")
    rel = con.sql(sql)
    cols = rel.columns
    rows = rel.fetchall()
    widths = [max(len(c), *(len(fmt(r[i])) for r in rows)) if rows else len(c)
              for i, c in enumerate(cols)]
    print("  " + "  ".join(c.ljust(widths[i]) for i, c in enumerate(cols)))
    for r in rows[:40]:
        print("  " + "  ".join(fmt(v).ljust(widths[i]) for i, v in enumerate(r)))
    if len(rows) > 40:
        print(f"  ... {len(rows)} rows")


def fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


@section("census")
def census(con):
    show(con, "row counts by source table", """
        select schema_name, table_name, estimated_size as approx_rows
        from duckdb_tables() order by 1, 2
    """)


@section("cost")
def cost_per_shipment(con):
    show(con, "shipment header cost vs charge lines", """
        with charges as (
            select shipment_id, sum(amount_usd) as charge_total
            from pangea.charge group by 1
        )
        select
            count(*)                                              as shipments,
            count(*) filter (where c.charge_total is null)        as no_charge_lines,
            round(sum(s.total_cost_usd), 0)                       as header_total,
            round(sum(c.charge_total), 0)                         as charge_total,
            count(*) filter (where abs(s.total_cost_usd - c.charge_total) < 0.01) as agree_to_cent,
            round(avg(c.charge_total - s.total_cost_usd), 2)      as mean_diff
        from pangea.shipment s left join charges c using (shipment_id)
    """)
    show(con, "charge mix", """
        select charge_code, count(*) as lines, round(sum(amount_usd), 0) as amount_usd,
               count(distinct currency) as currencies
        from pangea.charge group by 1 order by 3 desc
    """)


@section("otd")
def on_time_delivery(con):
    show(con, "on time against the carrier promise", """
        select count(*) as delivered,
               count(*) filter (where delivered_date <= estimated_delivery_date) as on_time,
               round(100.0 * count(*) filter (where delivered_date <= estimated_delivery_date)
                     / count(*), 1) as pct
        from pangea.shipment
        where delivered_date is not null and estimated_delivery_date is not null
    """)
    show(con, "on time against the customer request date", """
        with requested as (
            select "SOHNUM_0" as order_no, max("DEMDLVDAT_0") as requested
            from sage_x3."SORDERQ"
            where "DEMDLVDAT_0" > date '1900-01-01' group by 1
        )
        select count(*) as delivered_and_joinable,
               count(*) filter (where s.delivered_date <= r.requested) as on_time,
               round(100.0 * count(*) filter (where s.delivered_date <= r.requested)
                     / count(*), 1) as pct
        from pangea.shipment s
        join requested r on trim(s.reference_number) = trim(r.order_no)
        where s.delivered_date is not null
    """)
    show(con, "shipment status and date completeness", """
        select status, count(*) as shipments,
               count(*) filter (where delivered_date is not null) as has_delivered_date
        from pangea.shipment group by 1 order by 2 desc
    """)


@section("dso")
def dso(con):
    show(con, "settlement completeness", """
        select count(*) as invoices,
               count(*) filter (where "PAYDAT_0" = date '1753-01-01') as sentinel_unpaid,
               round(100.0 * count(*) filter (where "PAYDAT_0" = date '1753-01-01')
                     / count(*), 1) as pct_unpaid
        from sage_x3."SINVOICEV"
    """)
    show(con, "days to pay on settled invoices", """
        select round(avg(date_diff('day', "INVDAT_0", "PAYDAT_0")), 1) as mean_days,
               median(date_diff('day', "INVDAT_0", "PAYDAT_0"))        as median_days,
               min(date_diff('day', "INVDAT_0", "PAYDAT_0"))           as min_days,
               max(date_diff('day', "INVDAT_0", "PAYDAT_0"))           as max_days
        from sage_x3."SINVOICEV" where "PAYDAT_0" > date '1900-01-01'
    """)
    show(con, "what the sentinel does if you forget to filter it", """
        select round(avg(date_diff('day', "INVDAT_0", "PAYDAT_0")), 1) as mean_days_unguarded
        from sage_x3."SINVOICEV"
    """)


@section("blocked")
def blocked(con):
    show(con, "return rate: no returns object", """
        select (select count(distinct "SIVTYP_0") from sage_x3."SINVOICEV")            as invoice_types,
               (select count(*) from sage_x3."SINVOICED" where "AMTNOTLIN_0" < 0)      as negative_invoice_lines,
               (select count(*) from sage_x3."SORDERQ" where "QTY_0" < 0)              as negative_order_lines,
               (select count(distinct "VCRTYP_0") from sage_x3."STOJOU")               as movement_doc_types
    """)
    show(con, "stock movement types (local menu chapter 700)", """
        select j."TRSTYP_0" as code, m."TEXTE_0" as label, count(*) as movements
        from sage_x3."STOJOU" j
        left join sage_x3."APLSTD" m
          on m."CHAPTER_0" = 700 and m."CODE_0" = j."TRSTYP_0" and m."LANNUM_0" = 'ENG'
        group by 1, 2 order by 1
    """)
    show(con, "match rate: the AP side of the estate", """
        select (select count(*) from sage_x3."PORDERQ")                                as po_lines,
               (select count(*) from sage_x3."PORDERQ" where "RCPQTY_0" > 0)           as lines_received,
               (select count(*) from sage_x3."PORDERQ" where "RCPQTY_0" = "QTYUOM_0")  as qty_exact_match,
               (select count(distinct "JOU_0") from sage_x3."GACCENTRY")               as gl_journals,
               (select count(distinct "ACC_0") from sage_x3."GACCENTRYD")              as gl_accounts
    """)
    show(con, "inventory accuracy: adjustments are not counts", """
        select count(*) as adjustment_rows,
               count(*) filter (where "QTYSTU_0" < 0) as negative,
               count(*) filter (where "QTYSTU_0" > 0) as positive,
               round(sum("QTYSTU_0"), 0) as net_units
        from sage_x3."STOJOU" where "TRSTYP_0" = 3
    """)


@section("padding")
def padding(con):
    show(con, "CHAR padding by column", """
        select 'SORDERQ.ITMREF_0' as column_name,
               (select count(*) from sage_x3."SORDERQ" where "ITMREF_0" <> trim("ITMREF_0")) as padded_rows
        union all select 'SORDERP.ITMREF_0',
               (select count(*) from sage_x3."SORDERP" where "ITMREF_0" <> trim("ITMREF_0"))
        union all select 'STOJOU.ITMREF_0',
               (select count(*) from sage_x3."STOJOU" where "ITMREF_0" <> trim("ITMREF_0"))
        union all select 'SORDER.BPCORD_0',
               (select count(*) from sage_x3."SORDER" where "BPCORD_0" <> trim("BPCORD_0"))
        union all select 'ITMMASTER.ITMREF_0 (master, unpadded)',
               (select count(*) from sage_x3."ITMMASTER" where "ITMREF_0" <> trim("ITMREF_0"))
    """)
    show(con, "naive join vs trimmed join", """
        select (select count(*) from sage_x3."SORDERQ" q join sage_x3."ITMMASTER" m
                  on q."ITMREF_0" = m."ITMREF_0")                as naive_join_rows,
               (select count(*) from sage_x3."SORDERQ" q join sage_x3."ITMMASTER" m
                  on trim(q."ITMREF_0") = m."ITMREF_0")          as trimmed_join_rows
    """)


@section("xref")
def crosswalks(con):
    show(con, "shipment reference to X3 sales order", """
        select count(*) as shipments,
               count(*) filter (where reference_number is null) as null_reference,
               count(*) filter (where o."SOHNUM_0" is not null) as joins_to_order
        from pangea.shipment s
        left join sage_x3."SORDER" o on trim(s.reference_number) = trim(o."SOHNUM_0")
    """)
    show(con, "shipment customer_name to X3 customer name", """
        select count(*) as distinct_shipment_customers,
               count(c."BPCNUM_0") as matched
        from (select distinct customer_name as nm from pangea.shipment) s
        left join sage_x3."BPCUSTOMER" c on upper(trim(s.nm)) = upper(trim(c."BPCNAM_0"))
    """)
    show(con, "HubSpot company to X3 customer", """
        with hs as (
            select id,
                   upper(regexp_replace(regexp_replace(name, '[.,]', '', 'g'),
                         ' +(INC|LLC|LTD|CORP|CO|GROUP|COMPANY|ULC)$', '')) as k
            from hubspot.company
        ),
        x3 as (
            select "BPCNUM_0" as code,
                   upper(regexp_replace(regexp_replace("BPCNAM_0", '[.,]', '', 'g'),
                         ' +(INC|LLC|LTD|CORP|CO|GROUP|COMPANY|ULC)$', '')) as k
            from sage_x3."BPCUSTOMER"
        )
        select (select count(*) from hubspot.company) as hs_companies,
               (select count(*) from hubspot.company h
                  join sage_x3."BPCUSTOMER" c on upper(trim(h.name)) = upper(trim(c."BPCNAM_0")))
                                                     as exact_name_match,
               (select count(x3.code) from hs left join x3 using (k)) as normalised_match
    """)
    show(con, "HubSpot deal to X3 order", """
        select count(*) as deals,
               count(*) filter (where hs_is_closed_won) as closed_won,
               count(*) filter (where nullif(trim(erp_order_number), '') is not null) as has_reference,
               count(o."SOHNUM_0") as joins_as_is
        from hubspot.deal d
        left join sage_x3."SORDER" o on d.erp_order_number = o."SOHNUM_0"
    """)
    show(con, "X3 rep to Paycom employee (name is not a key)", """
        select count(*) as join_rows,
               count(distinct r."REPNUM_0") as distinct_reps,
               (select count(*) from sage_x3."REPRESENT") as reps_in_x3
        from sage_x3."REPRESENT" r
        join paycom.employee e
          on upper(trim(r."REPNAM_0"))
             = upper(trim(e.legal_last_name) || ' ' || trim(e.legal_first_name))
    """)
    show(con, "Paycom name collisions", """
        select count(*) as colliding_names from (
            select upper(trim(legal_last_name) || ' ' || trim(legal_first_name)) as k
            from paycom.employee group by 1 having count(*) > 1
        ) t
    """)


@section("currency")
def currency(con):
    show(con, "currency spread", """
        select 'SORDER' as tbl, "CUR_0" as currency, count(*) as rows from sage_x3."SORDER" group by 1,2
        union all
        select 'SINVOICEV', "CUR_0", count(*) from sage_x3."SINVOICEV" group by 1,2
        order by 1, 2
    """)
    show(con, "implied FX rate from the GL", """
        select h."CUR_0" as document_currency,
               round(d."AMTLOC_0" / nullif(d."AMTCUR_0", 0), 4) as implied_rate,
               count(*) as lines
        from sage_x3."GACCENTRYD" d
        join sage_x3."GACCENTRY" h on d."NUM_0" = h."NUM_0"
        group by 1, 2 order by 1, 3 desc
    """)


@section("events")
def events(con):
    show(con, "tracking events out of sequence", """
        with e as (
            select shipment_id, event_seq, event_ts,
                   lag(event_ts) over (partition by shipment_id order by event_seq) as prev_ts
            from pangea.tracking_event
        )
        select count(*) as events,
               count(*) filter (where prev_ts is not null and event_ts < prev_ts) as out_of_sequence,
               round(100.0 * count(*) filter (where prev_ts is not null and event_ts < prev_ts)
                     / count(*), 2) as pct
        from e
    """)
    show(con, "event codes", """
        select event_code, event_description, count(*) as events
        from pangea.tracking_event group by 1, 2 order by 3 desc
    """)


def main():
    wanted = sys.argv[1:] or list(SECTIONS)
    unknown = [w for w in wanted if w not in SECTIONS]
    if unknown:
        raise SystemExit(f"unknown section(s) {unknown}; available: {list(SECTIONS)}")
    con = duckdb.connect(DB, read_only=True)
    for name in wanted:
        print(f"\n{'=' * 70}\n== {name}\n{'=' * 70}")
        SECTIONS[name](con)


if __name__ == "__main__":
    main()
