-- Cleaning only: no business logic.
-- Grain: One row per goods receipt line.
with source as (
    select * from {{ ref('bronze_sage_x3__preceiptd') }}
),

cleaned as (

    select
        {{ clean_str('PTHNUM_0') }} as receipt_number,
        cast(PTDLIN_0 as bigint) as receipt_line_number,
        {{ clean_str('POHNUM_0') }} as purchase_order_number,
        cast(POPLIN_0 as bigint) as purchase_order_line_number,
        {{ clean_str('ITMREF_0') }} as item_code,
        {{ clean_str('PTHFCY_0') }} as receipt_site_code,
        cast(QTYUOM_0 as decimal(18, 4)) as received_qty,
        {{ x3_date('RCPDAT_0') }} as receipt_date

    from source

)

select * from cleaned
