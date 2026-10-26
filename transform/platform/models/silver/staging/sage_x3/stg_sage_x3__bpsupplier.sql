-- Cleaning only: no business logic.
-- Grain: One row per supplier account.
with source as (
    select * from {{ ref('bronze_sage_x3__bpsupplier') }}
),

cleaned as (

    select
        {{ clean_str('BPSNUM_0') }} as supplier_code,
        {{ clean_str('BPSNAM_0') }} as supplier_name,
        {{ clean_str('CUR_0') }} as currency_code,
        {{ clean_str('PTE_0') }} as payment_term_code,
        cast(LTI_0 as bigint) as lead_time_days,
        {{ clean_str('ACCCOD_0') }} as accounting_code,
        cast(UPDTICK_0 as bigint) as update_tick

    from source

)

select * from cleaned
