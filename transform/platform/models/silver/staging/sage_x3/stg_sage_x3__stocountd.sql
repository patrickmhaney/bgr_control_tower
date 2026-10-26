-- Cleaning only: no business logic.
-- Grain: One row per counted stock position.
with source as (
    select * from {{ ref('bronze_sage_x3__stocountd') }}
),

cleaned as (

    select
        {{ clean_str('SESNUM_0') }} as count_session_number,
        cast(CNTLIN_0 as bigint) as count_line_number,
        {{ clean_str('ITMREF_0') }} as item_code,
        {{ clean_str('STOFCY_0') }} as site_code,
        {{ clean_str('LOC_0') }} as location_code,
        {{ clean_str('LOT_0') }} as lot_code,
        cast(QTYTHEO_0 as decimal(18, 4)) as system_qty,
        cast(QTYCNT_0 as decimal(18, 4)) as counted_qty,
        cast(CNTSTA_0 as bigint) as count_line_status_code

    from source

),

decoded_count_line_status as (

    select
        base.*,
        menu.menu_label as count_line_status

    from cleaned as base
    left join {{ ref('stg_sage_x3__aplstd') }} as menu
        on menu.menu_chapter = 740
        and menu.menu_code = base.count_line_status_code
        and menu.language_code = 'ENG'

)

select * from decoded_count_line_status
