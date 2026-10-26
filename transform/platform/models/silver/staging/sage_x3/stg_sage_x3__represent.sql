-- Cleaning only: no business logic.
-- Grain: One row per sales representative.
with source as (
    select * from {{ ref('bronze_sage_x3__represent') }}
),

cleaned as (

    select
        {{ clean_str('REPNUM_0') }} as rep_code,
        {{ clean_str('REPNAM_0') }} as rep_name,
        {{ clean_str('FCY_0') }} as site_code,
        cast(REPTYP_0 as bigint) as rep_type_code,
        cast(UPDTICK_0 as bigint) as update_tick

    from source

)

select * from cleaned
