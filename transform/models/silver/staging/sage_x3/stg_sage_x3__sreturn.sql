-- Cleaning only: no business logic.
-- Grain: One row per customer return header.
with source as (
    select * from {{ ref('bronze_sage_x3__sreturn') }}
),

cleaned as (

    select
        {{ clean_str('SRHNUM_0') }} as return_number,
        {{ clean_str('SRHFCY_0') }} as site_code,
        {{ clean_str('BPCNUM_0') }} as customer_code,
        {{ x3_date('RTNDAT_0') }} as return_date,
        {{ clean_str('SOHNUM_0') }} as sales_order_number,
        {{ clean_str('SIVNUM_0') }} as invoice_number,
        cast(RTNSTA_0 as bigint) as return_status_code,
        cast(RTNREN_0 as bigint) as return_reason_code,
        {{ clean_str('CREUSR_0') }} as created_by,
        cast(UPDTICK_0 as bigint) as update_tick

    from source

),

decoded_return_status as (

    select
        base.*,
        menu.menu_label as return_status

    from cleaned as base
    left join {{ ref('stg_sage_x3__aplstd') }} as menu
        on menu.menu_chapter = 740
        and menu.menu_code = base.return_status_code
        and menu.language_code = 'ENG'

),

decoded_return_reason as (

    select
        base.*,
        menu.menu_label as return_reason

    from decoded_return_status as base
    left join {{ ref('stg_sage_x3__aplstd') }} as menu
        on menu.menu_chapter = 720
        and menu.menu_code = base.return_reason_code
        and menu.language_code = 'ENG'

)

select * from decoded_return_reason
