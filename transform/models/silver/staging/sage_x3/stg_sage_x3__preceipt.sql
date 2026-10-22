-- Cleaning only: no business logic.
-- Grain: One row per goods receipt header.
with source as (
    select * from {{ ref('bronze_sage_x3__preceipt') }}
),

cleaned as (

    select
        {{ clean_str('PTHNUM_0') }} as receipt_number,
        {{ clean_str('PTHFCY_0') }} as receipt_site_code,
        {{ clean_str('BPSNUM_0') }} as supplier_code,
        {{ clean_str('POHNUM_0') }} as purchase_order_number,
        {{ x3_date('RCPDAT_0') }} as receipt_date,
        cast(PTHTYP_0 as bigint) as receipt_type_code,
        {{ clean_str('CREUSR_0') }} as received_by,
        cast(UPDTICK_0 as bigint) as update_tick

    from source

)

select * from cleaned
