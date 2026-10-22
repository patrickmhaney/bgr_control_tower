-- Cleaning only: no business logic.
-- Grain: One row per legal entity.
with source as (
    select * from {{ ref('bronze_sage_x3__company') }}
),

cleaned as (

    select
        {{ clean_str('CPY_0') }} as company_code,
        {{ clean_str('CPYNAM_0') }} as company_name,
        {{ clean_str('CRY_0') }} as country_code,
        {{ clean_str('LEG_0') }} as legislation_code,
        cast(CPYLOG_0 as bigint) as is_logistics_flag

    from source

)

select * from cleaned
