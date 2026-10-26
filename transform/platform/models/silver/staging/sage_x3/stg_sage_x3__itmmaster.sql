-- Cleaning only: no business logic.
-- Grain: One row per item.
with source as (
    select * from {{ ref('bronze_sage_x3__itmmaster') }}
),

cleaned as (

    select
        {{ clean_str('ITMREF_0') }} as item_code,
        {{ clean_str('ITMDES1_0') }} as item_description,
        {{ clean_str('ITMDES2_0') }} as item_description_2,
        {{ clean_str('TCLCOD_0') }} as item_category_code,
        {{ clean_str('TSICOD_0') }} as statistical_group_1,
        {{ clean_str('TSICOD_1') }} as statistical_group_2,
        {{ clean_str('TSICOD_2') }} as statistical_group_3,
        {{ clean_str('STU_0') }} as stock_unit,
        cast(ITMSTA_0 as bigint) as item_status_code,
        cast(BASPRI_0 as decimal(18, 4)) as base_sales_price,
        cast(PURBASPRI_0 as decimal(18, 4)) as base_purchase_price,
        {{ clean_str('EANCOD_0') }} as ean_code,
        cast(ITMWEI_0 as decimal(18, 4)) as item_weight,
        {{ x3_date('CREDAT_0') }} as created_date,
        {{ x3_date('UPDDAT_0') }} as updated_date,
        {{ clean_str('CREUSR_0') }} as created_by,
        cast(UPDTICK_0 as bigint) as update_tick

    from source

),

decoded_item_status as (

    select
        base.*,
        menu.menu_label as item_status

    from cleaned as base
    left join {{ ref('stg_sage_x3__aplstd') }} as menu
        on menu.menu_chapter = 20
        and menu.menu_code = base.item_status_code
        and menu.language_code = 'ENG'

)

select * from decoded_item_status
