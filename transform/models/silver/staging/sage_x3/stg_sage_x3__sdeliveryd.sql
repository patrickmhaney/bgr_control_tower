-- Cleaning only: no business logic.
-- Grain: One row per delivery line.
with source as (
    select * from {{ ref('bronze_sage_x3__sdeliveryd') }}
),

cleaned as (

    select
        {{ clean_str('SDHNUM_0') }} as delivery_number,
        cast(SDDLIN_0 as bigint) as delivery_line_number,
        {{ clean_str('SOHNUM_0') }} as sales_order_number,
        cast(SOPLIN_0 as bigint) as sales_order_line_number,
        {{ clean_str('ITMREF_0') }} as item_code,
        {{ clean_str('STOFCY_0') }} as shipping_site_code,
        cast(QTY_0 as decimal(18, 4)) as delivered_qty,
        cast(NETPRI_0 as decimal(18, 4)) as net_unit_price

    from source

)

select * from cleaned
