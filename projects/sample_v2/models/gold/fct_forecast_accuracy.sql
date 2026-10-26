-- Grain: one row per item, location and month with an actual.
-- Feeds Forecast Accuracy (1 - weighted absolute percentage error). Netstock
-- plans 35 items the ERP does not have; they land as item UNKNOWN with the
-- Netstock code kept, rather than vanishing from the error total.

with accuracy as (

    select * from {{ ref('stg_netstock__forecast_accuracy') }}

),

items as (

    select item_code from {{ ref('stg_sage_x3__itmmaster') }}

)

select
    cast(a.period_start_date as date) as period_start_date,
    cast(case when i.item_code is null then 'UNKNOWN' else a.item_code end as varchar) as item_code,
    cast(a.item_code as varchar) as netstock_item_code,
    cast(coalesce(x.x3_site_code, 'UNKNOWN') as varchar) as site_code,
    cast(a.forecast_qty as decimal(18, 4)) as forecast_qty,
    cast(a.actual_qty as decimal(18, 4)) as actual_qty,
    cast(abs(a.actual_qty - a.forecast_qty) as decimal(18, 4)) as absolute_error_qty,
    cast(1 as integer) as forecast_line_count
from accuracy as a
left join items as i
    on i.item_code = a.item_code
left join {{ ref('site_code_crosswalk') }} as x
    on x.netstock_location_code = a.location_code
