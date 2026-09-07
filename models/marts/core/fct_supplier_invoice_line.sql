-- Grain: one row per supplier invoice line (NUM_0 + PIDLIN_0).
--
-- The atomic S2P fact. Match Rate reads is_three_way_matched; match_result
-- carries WHY a line failed, which is the column an AP manager actually works
-- from - a match rate on its own tells you there is a problem and nothing
-- about where to go.
--
-- Amounts are USD-only here. Every supplier invoice in this estate is USD, so
-- the _doc/_usd split that fct_sales_order_line carries would be two identical
-- columns pretending to be a decision. If a foreign-currency supplier appears,
-- this model gets the same fx treatment as the sales side and the metric
-- definition does not change.

with matched as (

    select * from {{ ref('int_supplier_invoice_match') }}

),

final as (

    select
        supplier_invoice_number,
        supplier_invoice_line_number,

        -- Conformed dimension keys
        cast(strftime(invoice_date, '%Y%m%d') as integer)    as invoice_date_key,
        cast(strftime(accounting_date, '%Y%m%d') as integer) as accounting_date_key,
        coalesce(item_code, 'UNKNOWN')                       as item_code,
        coalesce(site_code, 'UNKNOWN')                       as site_code,

        -- Degenerate attributes. Supplier is not a conformed dimension in this
        -- model - it appears on one fact - so it stays a degenerate attribute
        -- until a second process needs it.
        supplier_code,
        purchase_order_number,
        receipt_number,
        currency_code,
        invoice_status_code,

        -- Dates
        invoice_date,
        accounting_date,
        receipt_date,
        last_receipt_date,

        -- Measures
        invoiced_qty,
        received_qty,
        total_received_qty,
        ordered_qty,
        invoiced_unit_price,
        ordered_unit_price,
        cast(line_net_amount as decimal(18, 4))              as line_net_amount_usd,
        qty_variance,
        price_variance,
        cast(qty_variance_pct as decimal(18, 4))             as qty_variance_pct,
        cast(price_variance_pct as decimal(18, 4))           as price_variance_pct,
        receipt_count,

        -- Flags
        match_result,
        is_three_way_matched,
        purchase_order_number is null                        as is_maverick_spend,
        receipt_count > 1                                    as is_multi_delivery

    from matched

)

select * from final
