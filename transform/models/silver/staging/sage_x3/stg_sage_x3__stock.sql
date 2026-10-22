-- Cleaning only: no business logic.
-- Grain: One row per item, site, lot and location.
with source as (
    select * from {{ ref('bronze_sage_x3__stock') }}
),

cleaned as (

    select
        {{ clean_str('STOFCY_0') }} as site_code,
        {{ clean_str('ITMREF_0') }} as item_code,
        {{ clean_str('LOT_0') }} as lot_code,
        {{ clean_str('LOC_0') }} as location_code,
        cast(QTYSTU_0 as decimal(18, 4)) as on_hand_qty,
        {{ clean_str('STA_0') }} as stock_status,
        {{ clean_str('OWNER_0') }} as owner_code,
        cast(UPDTICK_0 as bigint) as update_tick

    from source

)

select * from cleaned
