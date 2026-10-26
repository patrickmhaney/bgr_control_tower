-- Cleaning only: no business logic.
-- Grain: One row per sales invoice line.
with source as (
    select * from {{ ref('bronze_sage_x3__sinvoiced') }}
),

cleaned as (

    select
        {{ clean_str('NUM_0') }} as invoice_number,
        cast(SIDLIN_0 as bigint) as invoice_line_number,
        {{ clean_str('ITMREF_0') }} as item_code,
        {{ clean_str('ITMDES1_0') }} as item_description_at_invoice,
        cast(QTY_0 as decimal(18, 4)) as invoiced_qty,
        cast(NETPRI_0 as decimal(18, 4)) as net_unit_price,
        cast(AMTNOTLIN_0 as decimal(18, 4)) as line_net_amount,
        {{ clean_str('SOHNUM_0') }} as sales_order_number,
        cast(SOPLIN_0 as bigint) as sales_order_line_number,
        {{ clean_str('STOFCY_0') }} as shipping_site_code

    from source

)

select * from cleaned
