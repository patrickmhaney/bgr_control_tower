-- Cleaning only: no business logic.
-- Grain: One row per GL journal header.
with source as (
    select * from {{ ref('bronze_sage_x3__gaccentry') }}
),

cleaned as (

    select
        {{ clean_str('NUM_0') }} as journal_entry_number,
        {{ clean_str('TYP_0') }} as entry_type_code,
        {{ clean_str('JOU_0') }} as journal_code,
        {{ clean_str('CPY_0') }} as company_code,
        {{ clean_str('FCY_0') }} as site_code,
        {{ x3_date('ACCDAT_0') }} as accounting_date,
        {{ clean_str('CUR_0') }} as currency_code,
        {{ clean_str('DES_0') }} as description,
        {{ clean_str('VCRNUM_0') }} as source_document_number,
        cast(STA_0 as bigint) as entry_status_code,
        cast(UPDTICK_0 as bigint) as update_tick

    from source

)

select * from cleaned
