-- Cleaning only: no business logic.
-- Grain: One row per GL journal line.
with source as (
    select * from {{ ref('bronze_sage_x3__gaccentryd') }}
),

cleaned as (

    select
        {{ clean_str('NUM_0') }} as journal_entry_number,
        cast(LIN_0 as bigint) as journal_line_number,
        {{ clean_str('ACC_0') }} as gl_account_code,
        cast(SNS_0 as bigint) as debit_credit_sign,
        cast(AMTCUR_0 as decimal(18, 4)) as amount_document_currency,
        cast(AMTLOC_0 as decimal(18, 4)) as amount_company_currency,
        {{ clean_str('BPR_0') }} as partner_code,
        {{ clean_str('CPY_0') }} as company_code,
        {{ clean_str('FCY_0') }} as site_code,
        {{ clean_str('DSP_0') }} as dimension_code,
        {{ x3_date('ACCDAT_0') }} as accounting_date

    from source

)

select * from cleaned
