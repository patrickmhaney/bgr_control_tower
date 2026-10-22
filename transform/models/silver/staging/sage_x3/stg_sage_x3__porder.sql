-- Cleaning only: no business logic.
-- Grain: One row per purchase order header.
with source as (
    select * from {{ ref('bronze_sage_x3__porder') }}
),

cleaned as (

    select
        {{ clean_str('POHNUM_0') }} as purchase_order_number,
        {{ clean_str('POHFCY_0') }} as purchase_site_code,
        {{ clean_str('BPSNUM_0') }} as supplier_code,
        {{ x3_date('ORDDAT_0') }} as order_date,
        cast(ORDSTA_0 as bigint) as order_status_code,
        {{ clean_str('CUR_0') }} as currency_code,
        {{ clean_str('CREUSR_0') }} as created_by,
        cast(UPDTICK_0 as bigint) as update_tick

    from source

),

decoded_order_status as (

    select
        base.*,
        menu.menu_label as order_status

    from cleaned as base
    left join {{ ref('stg_sage_x3__aplstd') }} as menu
        on menu.menu_chapter = 415
        and menu.menu_code = base.order_status_code
        and menu.language_code = 'ENG'

)

select * from decoded_order_status
