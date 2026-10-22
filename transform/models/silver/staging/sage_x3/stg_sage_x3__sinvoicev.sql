-- Cleaning only: no business logic.
-- Grain: One row per sales invoice header.
with source as (
    select * from {{ ref('bronze_sage_x3__sinvoicev') }}
),

cleaned as (

    select
        {{ clean_str('NUM_0') }} as invoice_number,
        {{ clean_str('SIVTYP_0') }} as invoice_type_code,
        {{ x3_date('INVDAT_0') }} as invoice_date,
        {{ clean_str('BPR_0') }} as customer_code,
        {{ clean_str('SALFCY_0') }} as sales_site_code,
        {{ clean_str('CUR_0') }} as currency_code,
        cast(AMTNOTLIN_0 as decimal(18, 4)) as invoice_net_amount,
        cast(AMTTAXLIN_0 as decimal(18, 4)) as invoice_tax_amount,
        cast(AMTATILIN_0 as decimal(18, 4)) as invoice_gross_amount,
        cast(INVSTA_0 as bigint) as invoice_status_code,
        {{ x3_date('PAYDAT_0') }} as payment_date,
        {{ x3_date('ACCDAT_0') }} as accounting_date,
        cast(UPDTICK_0 as bigint) as update_tick

    from source

)

select * from cleaned
