-- Cleaning only: no business logic.
-- Grain: One row per Netstock supplier.
with source as (
    select * from {{ ref('bronze_netstock__supplier') }}
),

cleaned as (

    select
        {{ clean_str('supplier_code') }} as supplier_code,
        {{ clean_str('supplier_name') }} as supplier_name,
        cast(lead_time_days as bigint) as lead_time_days,
        cast(min_order_value as decimal(18, 4)) as min_order_value,
        {{ clean_str('source_system') }} as source_system

    from source

)

select * from cleaned
