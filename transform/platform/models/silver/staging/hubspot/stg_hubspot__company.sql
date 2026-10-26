-- Cleaning only: no business logic.
-- Grain: One row per HubSpot company.
with source as (
    select * from {{ ref('bronze_hubspot__company') }}
),

cleaned as (

    select
        {{ clean_str('id') }} as company_id,
        {{ clean_str('name') }} as company_name,
        {{ clean_str('domain') }} as domain,
        {{ clean_str('industry') }} as industry,
        {{ clean_str('country') }} as country,
        try_cast({{ clean_str('numberofemployees') }} as double) as employee_count,
        try_cast({{ clean_str('annualrevenue') }} as double) as annual_revenue,
        {{ clean_str('hubspot_owner_id') }} as owner_id,
        createdate as created_date,
        hs_lastmodifieddate as last_modified_date,
        cast(archived as boolean) as is_archived

    from source

)

select * from cleaned
