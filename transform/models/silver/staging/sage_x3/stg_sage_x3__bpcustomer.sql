-- Cleaning only: no business logic.
-- Grain: One row per customer account.
with source as (
    select * from {{ ref('bronze_sage_x3__bpcustomer') }}
),

cleaned as (

    select
        {{ clean_str('BPCNUM_0') }} as customer_code,
        {{ clean_str('BPCNAM_0') }} as customer_name,
        {{ clean_str('BPCGRU_0') }} as customer_group_code,
        {{ clean_str('CUR_0') }} as currency_code,
        {{ clean_str('PTE_0') }} as payment_term_code,
        cast(BPCSNC_0 as decimal(18, 4)) as credit_limit_amount,
        cast(OSTCTL_0 as bigint) as credit_control_code,
        {{ clean_str('ACCCOD_0') }} as accounting_code,
        {{ clean_str('REP_0') }} as primary_rep_code,
        {{ clean_str('REP_1') }} as secondary_rep_code,
        {{ x3_date('CREDAT_0') }} as created_date,
        {{ x3_date('UPDDAT_0') }} as updated_date,
        cast(UPDTICK_0 as bigint) as update_tick

    from source

)

select * from cleaned
