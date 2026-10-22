-- Cleaning only: no business logic.
-- Grain: One row per inventory count session.
with source as (
    select * from {{ ref('bronze_sage_x3__stocount') }}
),

cleaned as (

    select
        {{ clean_str('SESNUM_0') }} as count_session_number,
        {{ clean_str('STOFCY_0') }} as site_code,
        {{ x3_date('CNTDAT_0') }} as count_date,
        cast(CNTTYP_0 as bigint) as count_type_code,
        cast(SESSTA_0 as bigint) as session_status_code,
        {{ clean_str('CREUSR_0') }} as counted_by,
        cast(UPDTICK_0 as bigint) as update_tick

    from source

),

decoded_count_type as (

    select
        base.*,
        menu.menu_label as count_type

    from cleaned as base
    left join {{ ref('stg_sage_x3__aplstd') }} as menu
        on menu.menu_chapter = 730
        and menu.menu_code = base.count_type_code
        and menu.language_code = 'ENG'

),

decoded_session_status as (

    select
        base.*,
        menu.menu_label as session_status

    from decoded_count_type as base
    left join {{ ref('stg_sage_x3__aplstd') }} as menu
        on menu.menu_chapter = 740
        and menu.menu_code = base.session_status_code
        and menu.language_code = 'ENG'

)

select * from decoded_session_status
