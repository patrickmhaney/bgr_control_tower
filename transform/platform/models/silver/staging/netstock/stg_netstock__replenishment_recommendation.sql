-- Cleaning only: no business logic.
-- Grain: One row per recommendation.
with source as (
    select * from {{ ref('bronze_netstock__replenishment_recommendation') }}
),

cleaned as (

    select
        {{ clean_str('recommendation_id') }} as recommendation_id,
        {{ clean_str('item_code') }} as item_code,
        {{ clean_str('location_code') }} as location_code,
        cast(recommended_qty as decimal(18, 4)) as recommended_qty,
        recommended_order_date as recommended_order_date,
        required_date as required_date,
        {{ clean_str('supplier_code') }} as supplier_code,
        {{ clean_str('status') }} as status,
        {{ clean_str('erp_po_number') }} as erp_purchase_order_number,
        generated_at as generated_date

    from source

)

select * from cleaned
