-- Cleaning only: no business logic.
-- Grain: One row per item, location and forecast period.
with source as (
    select * from {{ ref('bronze_netstock__forecast') }}
),

cleaned as (

    select
        {{ clean_str('item_code') }} as item_code,
        {{ clean_str('location_code') }} as location_code,
        period_start as period_start_date,
        {{ clean_str('period_type') }} as period_type,
        cast(forecast_qty as decimal(18, 4)) as forecast_qty,
        {{ clean_str('forecast_method') }} as forecast_method,
        generated_at as generated_date

    from source

)

select * from cleaned
