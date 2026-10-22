-- Grain: one row per item. The X3 item master, with Netstock planning
-- attributes summarised across locations.

with item as (

    select * from {{ ref('stg_sage_x3__itmmaster') }}

),

planning as (

    select
        item_code,
        min(abc_class) as best_abc_class,
        min(xyz_class) as best_xyz_class,
        count(*) as planned_location_count,
        max(case when stockout_risk = 'HIGH' then 1 else 0 end) as has_high_stockout_risk,
        max(last_sync_date) as netstock_last_sync_date
    from {{ ref('stg_netstock__item_location') }}
    group by item_code

)

select
    cast(i.item_code as varchar) as item_code,
    cast(i.item_description as varchar) as item_description,
    cast(i.item_category_code as varchar) as item_category_code,
    cast(i.statistical_group_1 as varchar) as statistical_group,
    cast(i.stock_unit as varchar) as stock_unit,
    cast(i.item_status as varchar) as item_status,
    cast({{ flag("i.item_status = 'Active'") }} as integer) as is_active_item,
    cast(i.base_sales_price as decimal(18, 4)) as base_sales_price,
    cast(i.base_purchase_price as decimal(18, 4)) as base_purchase_price,
    cast(p.best_abc_class as varchar) as best_abc_class,
    cast(p.best_xyz_class as varchar) as best_xyz_class,
    cast(coalesce(p.planned_location_count, 0) as integer) as planned_location_count,
    cast(coalesce(p.has_high_stockout_risk, 0) as integer) as has_high_stockout_risk,
    cast(p.netstock_last_sync_date as date) as netstock_last_sync_date,
    cast({{ flag('p.item_code is not null') }} as integer) as is_planned_in_netstock
from item as i
left join planning as p
    on p.item_code = i.item_code

union all

select 'UNKNOWN', 'Unresolved', null, null, null, null, 0, null, null, null, null, 0, 0, null, 0
