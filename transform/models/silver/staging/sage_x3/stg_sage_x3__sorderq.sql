-- Cleaning only: no business logic.
-- Grain: One row per sales order line (quantity side).
with source as (
    select * from {{ ref('bronze_sage_x3__sorderq') }}
),

cleaned as (

    select
        {{ clean_str('SOHNUM_0') }} as sales_order_number,
        cast(SOPLIN_0 as bigint) as sales_order_line_number,
        cast(SOQSEQ_0 as bigint) as sales_order_line_sequence,
        {{ clean_str('ITMREF_0') }} as item_code,
        {{ clean_str('STOFCY_0') }} as shipping_site_code,
        cast(QTY_0 as decimal(18, 4)) as ordered_qty,
        {{ x3_date('DEMDLVDAT_0') }} as requested_delivery_date,
        cast(SHTQTY_0 as decimal(18, 4)) as shortage_qty,
        {{ clean_str('UOM_0') }} as unit_of_measure,
        cast(UPDTICK_0 as bigint) as update_tick

    from source

)

select * from cleaned
