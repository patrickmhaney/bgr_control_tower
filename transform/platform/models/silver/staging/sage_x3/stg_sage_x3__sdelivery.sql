-- Cleaning only: no business logic.
-- Grain: One row per delivery (one shipment of a sales order).
with source as (
    select * from {{ ref('bronze_sage_x3__sdelivery') }}
),

cleaned as (

    select
        {{ clean_str('SDHNUM_0') }} as delivery_number,
        {{ clean_str('STOFCY_0') }} as shipping_site_code,
        {{ clean_str('SALFCY_0') }} as sales_site_code,
        {{ clean_str('BPCORD_0') }} as customer_code,
        {{ clean_str('SOHNUM_0') }} as sales_order_number,
        {{ x3_date('SHIDAT_0') }} as ship_date,
        {{ x3_date('DLVDAT_0') }} as delivered_date,
        cast(CFMFLG_0 as bigint) = 2 as is_confirmed,
        {{ clean_str('CREUSR_0') }} as created_by

    from source

)

select * from cleaned
