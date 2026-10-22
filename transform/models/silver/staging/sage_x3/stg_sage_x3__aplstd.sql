-- Cleaning only: no business logic.
-- Grain: One row per local menu chapter, code and language.
with source as (
    select * from {{ ref('bronze_sage_x3__aplstd') }}
),

cleaned as (

    select
        cast(CHAPTER_0 as bigint) as menu_chapter,
        cast(CODE_0 as bigint) as menu_code,
        {{ clean_str('LANNUM_0') }} as language_code,
        {{ clean_str('TEXTE_0') }} as menu_label

    from source

)

select * from cleaned
