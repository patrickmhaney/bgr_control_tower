-- Cleaning only: no business logic.
-- Grain: One row per X3 user.
with source as (
    select * from {{ ref('bronze_sage_x3__autilis') }}
),

cleaned as (

    select
        {{ clean_str('USR_0') }} as user_code,
        {{ clean_str('NOMUSR_0') }} as user_name,
        lower({{ clean_str('ADDEML_0') }}) as email,
        {{ clean_str('PRFFCT_0') }} as function_profile,
        {{ clean_str('FCY_0') }} as site_code,
        cast(ENAFLG_0 as bigint) = 2 as is_enabled

    from source

)

select * from cleaned
