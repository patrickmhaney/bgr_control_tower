-- Cleaning only: no business logic.
-- Grain: One row per business partner and address code.
with source as (
    select * from {{ ref('bronze_sage_x3__bpaddress') }}
),

cleaned as (

    select
        cast(BPATYP_0 as bigint) as partner_type_code,
        {{ clean_str('BPANUM_0') }} as partner_code,
        {{ clean_str('BPAADD_0') }} as address_code,
        {{ clean_str('BPADES_0') }} as address_description,
        {{ clean_str('ADDLIG_0') }} as address_line_1,
        {{ clean_str('ADDLIG_1') }} as address_line_2,
        {{ clean_str('CTY_0') }} as city,
        {{ clean_str('SAT_0') }} as state_province,
        {{ clean_str('POSCOD_0') }} as postal_code,
        {{ clean_str('CRY_0') }} as country_code,
        {{ clean_str('TEL_0') }} as phone

    from source

)

select * from cleaned
