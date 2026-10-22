-- Cleaning only: no business logic.
-- Grain: One row per business partner.
with source as (
    select * from {{ ref('bronze_sage_x3__bpartner') }}
),

cleaned as (

    select
        {{ clean_str('BPRNUM_0') }} as partner_code,
        {{ clean_str('BPRNAM_0') }} as partner_name,
        {{ clean_str('BPRNAM_1') }} as partner_name_2,
        cast(BPCFLG_0 as bigint) as is_customer_code,
        cast(BPSFLG_0 as bigint) as is_supplier_code,
        {{ clean_str('CRY_0') }} as country_code,
        {{ clean_str('CUR_0') }} as currency_code,
        cast(BPRLOG_0 as bigint) as is_active_code,
        cast(UPDTICK_0 as bigint) as update_tick,
        cast(BPCFLG_0 = 2 as boolean) as is_customer,
        cast(BPSFLG_0 = 2 as boolean) as is_supplier

    from source

)

select * from cleaned
