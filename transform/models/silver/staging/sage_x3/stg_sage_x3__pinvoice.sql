-- Cleaning only: no business logic.
-- Grain: One row per supplier invoice header.
with source as (
    select * from {{ ref('bronze_sage_x3__pinvoice') }}
),

cleaned as (

    select
        {{ clean_str('NUM_0') }} as supplier_invoice_number,
        {{ clean_str('PIVTYP_0') }} as invoice_type_code,
        {{ clean_str('BPSNUM_0') }} as supplier_code,
        {{ clean_str('BPSINV_0') }} as supplier_document_number,
        {{ x3_date('INVDAT_0') }} as invoice_date,
        {{ x3_date('ACCDAT_0') }} as accounting_date,
        {{ clean_str('PIHFCY_0') }} as site_code,
        {{ clean_str('CUR_0') }} as currency_code,
        cast(AMTNOTLIN_0 as decimal(18, 4)) as net_amount,
        cast(AMTTAXLIN_0 as decimal(18, 4)) as tax_amount,
        cast(AMTATILIN_0 as decimal(18, 4)) as gross_amount,
        cast(INVSTA_0 as bigint) as invoice_status_code,
        cast(UPDTICK_0 as bigint) as update_tick

    from source

)

select * from cleaned
