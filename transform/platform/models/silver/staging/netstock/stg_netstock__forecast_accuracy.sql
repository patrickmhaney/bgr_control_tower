-- Cleaning only: no business logic.
-- Grain: One row per item, location and period.
with source as (
    select * from {{ ref('bronze_netstock__forecast_accuracy') }}
),

cleaned as (

    select
        {{ clean_str('item_code') }} as item_code,
        {{ clean_str('location_code') }} as location_code,
        period_start as period_start_date,
        cast(forecast_qty as decimal(18, 4)) as forecast_qty,
        cast(actual_qty as decimal(18, 4)) as actual_qty,
        cast(abs_pct_error as decimal(18, 4)) as abs_pct_error

    from source

)

select * from cleaned
