-- Cleaning only: no business logic.
-- Grain: One row per site (X3 facility).
with source as (
    select * from {{ ref('bronze_sage_x3__facility') }}
),

cleaned as (

    select
        {{ clean_str('FCY_0') }} as site_code,
        {{ clean_str('FCYSHO_0') }} as site_short_name,
        {{ clean_str('FCYNAM_0') }} as site_name,
        {{ clean_str('LEGCPY_0') }} as company_code,
        {{ clean_str('CRY_0') }} as country_code,
        {{ clean_str('CTY_0') }} as city,
        {{ clean_str('SAT_0') }} as state_province,
        cast(FCYSTO_0 as bigint) as is_stock_site_code,
        cast(FCYSAL_0 as bigint) as is_sales_site_code,
        cast(FCYPUR_0 as bigint) as is_purchase_site_code,
        cast(FCYSTO_0 = 2 as boolean) as is_stock_site,
        cast(FCYSAL_0 = 2 as boolean) as is_sales_site,
        cast(FCYPUR_0 = 2 as boolean) as is_purchase_site

    from source

)

select * from cleaned
