-- Grain: one row per site.
--
-- Three sites and three different naming conventions. X3 is the conformed key;
-- the Paycom code arrives through a seed because no source relates the two and
-- deriving the relationship would mean inventing it.

with facility as (

    select
        site_code,
        site_short_name,
        site_name,
        company_code,
        country_code,
        city,
        state_province,
        is_stock_site,
        is_sales_site,
        is_purchase_site

    from {{ ref('stg_sage_x3__facility') }}

),

company as (

    select
        company_code,
        company_name,
        country_code as company_country_code,
        legislation_code

    from {{ ref('stg_sage_x3__company') }}

),

crosswalk as (

    select
        x3_site_code,
        paycom_location_code,
        netstock_location_code

    from {{ ref('site_code_crosswalk') }}

),

-- An UNKNOWN member, and every fact foreign key coalesced to it.
--
-- Without one, an unresolved key lands as null. `relationships` ignores nulls
-- so it still passes, `not_null` on the fact starts failing the build, and in
-- Power BI the rows collect on a blank dimension row that reads to a user as a
-- real member. With one, the existing tests keep passing and start meaning
-- "every fact is attributable", which is the assertion actually wanted.
--
-- Nothing is unresolved today. Customer resolution is 100% only because
-- pangea.shipment.customer_name happens to match all 220 distinct ERP names -
-- a coincidence open question 13 exists to check.

unknown_member as (

    select
        'UNKNOWN'                    as site_code,
        'UNKNOWN'                    as site_short_name,
        'Unresolved'                 as site_name,
        cast(null as varchar)        as city,
        cast(null as varchar)        as state_province,
        cast(null as varchar)        as country_code,
        false                        as is_stock_site,
        false                        as is_sales_site,
        false                        as is_purchase_site,
        cast(null as varchar)        as company_code,
        cast(null as varchar)        as company_name,
        cast(null as varchar)        as legislation_code,
        cast(null as varchar)        as paycom_location_code,
        cast(null as varchar)        as netstock_location_code

),

final as (

    select
        facility.site_code,
        facility.site_short_name,
        facility.site_name,
        facility.city,
        facility.state_province,
        facility.country_code,
        facility.is_stock_site,
        facility.is_sales_site,
        facility.is_purchase_site,
        company.company_code,
        company.company_name,
        company.legislation_code,
        crosswalk.paycom_location_code,
        crosswalk.netstock_location_code

    from facility
    left join company on company.company_code = facility.company_code
    left join crosswalk on crosswalk.x3_site_code = facility.site_code

)

select * from final
union all
select * from unknown_member
