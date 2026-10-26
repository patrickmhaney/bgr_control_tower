-- Cleaning only: no business logic.
-- Grain: One row per item and location.
with source as (
    select * from {{ ref('bronze_netstock__item_location') }}
),

cleaned as (

    select
        {{ clean_str('item_code') }} as item_code,
        {{ clean_str('location_code') }} as location_code,
        {{ clean_str('description') }} as item_description,
        {{ clean_str('abc_class') }} as abc_class,
        {{ clean_str('xyz_class') }} as xyz_class,
        {{ clean_str('policy') }} as replenishment_policy,
        cast(lead_time_days as bigint) as lead_time_days,
        cast(safety_stock_qty as decimal(18, 4)) as safety_stock_qty,
        cast(reorder_point_qty as decimal(18, 4)) as reorder_point_qty,
        cast(min_order_qty as decimal(18, 4)) as min_order_qty,
        {{ clean_str('supplier_code') }} as supplier_code,
        cast(on_hand_qty as decimal(18, 4)) as on_hand_qty,
        cast(on_order_qty as decimal(18, 4)) as on_order_qty,
        cast(excess_value as decimal(18, 4)) as excess_value,
        {{ clean_str('stockout_risk') }} as stockout_risk,
        last_sync_at as last_sync_date

    from source

)

select * from cleaned
