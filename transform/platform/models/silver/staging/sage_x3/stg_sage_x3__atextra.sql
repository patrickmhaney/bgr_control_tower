-- Cleaning only: no business logic.
-- Grain: One row per translated field value.
with source as (
    select * from {{ ref('bronze_sage_x3__atextra') }}
),

cleaned as (

    select
        {{ clean_str('CODFIC_0') }} as table_code,
        {{ clean_str('ZONE_0') }} as field_code,
        {{ clean_str('LANNUM_0') }} as language_code,
        {{ clean_str('IDENT1_0') }} as key_1,
        {{ clean_str('IDENT2_0') }} as key_2,
        {{ clean_str('TEXTE_0') }} as translated_text

    from source

)

select * from cleaned
