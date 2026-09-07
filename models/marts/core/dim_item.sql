-- Grain: one row per item.
--
-- X3 is the master. Netstock planning attributes are joined on where they
-- exist, at item level - Netstock's grain is item x location, so the planning
-- attributes carried here are the ones that do not vary by location, and the
-- per-site parameters stay where they belong.
--
-- Note ITMDES1_0 on the transaction tables is denormalised at order time and
-- drifts from this description. Neither is wrong; they answer different
-- questions, and the one here is "what is this item called now".

with item as (

    select
        item_code,
        item_description,
        item_description_2,
        item_category_code,
        statistical_group_1,
        statistical_group_2,
        statistical_group_3,
        stock_unit,
        item_status_code,
        item_status,
        base_sales_price,
        base_purchase_price,
        ean_code,
        item_weight,
        created_date,
        updated_date

    from {{ ref('stg_sage_x3__itmmaster') }}

),

planning as (

    -- Netstock classifies at item x location. An item can carry a different
    -- ABC class per site, so the item-level view has to state a rule: the
    -- strongest class the item holds anywhere. Aggregating to a single letter
    -- would otherwise be a silent choice.
    select
        item_code,
        min(abc_class)                        as best_abc_class,
        min(xyz_class)                        as best_xyz_class,
        count(*)                              as planned_location_count,
        bool_or(stockout_risk = 'HIGH')       as has_high_stockout_risk,
        max(last_sync_date)                   as netstock_last_sync_date

    from {{ ref('stg_netstock__item_location') }}
    group by 1

),

unknown_member as (

    select
        'UNKNOWN'                    as item_code,
        'Unresolved'                 as item_description,
        cast(null as varchar)        as item_description_2,
        cast(null as varchar)        as item_category_code,
        cast(null as varchar)        as statistical_group_1,
        cast(null as varchar)        as statistical_group_2,
        cast(null as varchar)        as statistical_group_3,
        cast(null as varchar)        as stock_unit,
        cast(null as varchar)        as item_status,
        false                        as is_active_item,
        cast(null as decimal(18, 4)) as base_sales_price,
        cast(null as decimal(18, 4)) as base_purchase_price,
        cast(null as decimal(18, 4)) as item_weight,
        cast(null as varchar)        as ean_code,
        cast(null as date)           as created_date,
        cast(null as date)           as updated_date,
        cast(null as varchar)        as best_abc_class,
        cast(null as varchar)        as best_xyz_class,
        0                            as planned_location_count,
        false                        as has_high_stockout_risk,
        cast(null as date)           as netstock_last_sync_date,
        false                        as is_planned_in_netstock

),

final as (

    select
        item.item_code,
        item.item_description,
        item.item_description_2,
        item.item_category_code,
        item.statistical_group_1,
        item.statistical_group_2,
        item.statistical_group_3,
        item.stock_unit,
        item.item_status,
        item.item_status = 'Active'                        as is_active_item,
        item.base_sales_price,
        item.base_purchase_price,
        item.item_weight,
        item.ean_code,
        item.created_date,
        item.updated_date,
        planning.best_abc_class,
        planning.best_xyz_class,
        coalesce(planning.planned_location_count, 0)       as planned_location_count,
        coalesce(planning.has_high_stockout_risk, false)   as has_high_stockout_risk,
        planning.netstock_last_sync_date,
        planning.item_code is not null                     as is_planned_in_netstock

    from item
    left join planning on planning.item_code = item.item_code

)

select * from final
union all
select * from unknown_member
