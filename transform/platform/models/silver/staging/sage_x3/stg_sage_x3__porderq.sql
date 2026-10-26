-- Cleaning only: no business logic.
-- Grain: One row per purchase order line.
with source as (
    select * from {{ ref('bronze_sage_x3__porderq') }}
),

cleaned as (

    select
        {{ clean_str('POHNUM_0') }} as purchase_order_number,
        cast(POPLIN_0 as bigint) as purchase_order_line_number,
        cast(POQSEQ_0 as bigint) as purchase_order_line_sequence,
        {{ clean_str('ITMREF_0') }} as item_code,
        {{ clean_str('POHFCY_0') }} as purchase_site_code,
        cast(QTYUOM_0 as decimal(18, 4)) as ordered_qty,
        {{ x3_date('EXTRCPDAT_0') }} as expected_receipt_date,
        cast(RCPQTY_0 as decimal(18, 4)) as received_qty,
        {{ x3_date('RCPDAT_0') }} as actual_receipt_date,
        cast(NETPRI_0 as decimal(18, 4)) as net_unit_price,
        cast(UPDTICK_0 as bigint) as update_tick

    from source

)

select * from cleaned
