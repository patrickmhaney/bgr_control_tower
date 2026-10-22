-- Cleaning only: no business logic.
-- Grain: One row per stock movement (STOJOU.ROWID).
with source as (
    select * from {{ ref('bronze_sage_x3__stojou') }}
),

cleaned as (

    select
        cast(ROWID as bigint) as stock_movement_id,
        {{ clean_str('ITMREF_0') }} as item_code,
        {{ clean_str('STOFCY_0') }} as site_code,
        {{ x3_date('IPTDAT_0') }} as movement_date,
        cast(TRSTYP_0 as bigint) as movement_type_code,
        cast(QTYSTU_0 as decimal(18, 4)) as movement_qty,
        {{ clean_str('VCRNUM_0') }} as document_number,
        {{ clean_str('VCRTYP_0') }} as document_type,
        {{ clean_str('LOT_0') }} as lot_code,
        {{ clean_str('CREUSR_0') }} as created_by,
        cast(UPDTICK_0 as bigint) as update_tick

    from source

),

decoded_movement_type as (

    select
        base.*,
        menu.menu_label as movement_type

    from cleaned as base
    left join {{ ref('stg_sage_x3__aplstd') }} as menu
        on menu.menu_chapter = 700
        and menu.menu_code = base.movement_type_code
        and menu.language_code = 'ENG'

)

select * from decoded_movement_type
