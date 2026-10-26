-- Cleaning only: no business logic.
-- Grain: One row per HubSpot contact.
with source as (
    select * from {{ ref('bronze_hubspot__contact') }}
),

cleaned as (

    select
        {{ clean_str('id') }} as contact_id,
        {{ clean_str('email') }} as email,
        {{ clean_str('firstname') }} as first_name,
        {{ clean_str('lastname') }} as last_name,
        {{ clean_str('jobtitle') }} as job_title,
        {{ clean_str('phone') }} as phone,
        {{ clean_str('lifecyclestage') }} as lifecycle_stage,
        {{ clean_str('hs_lead_status') }} as lead_status,
        {{ clean_str('hubspot_owner_id') }} as owner_id,
        {{ clean_str('associatedcompanyid') }} as company_id,
        createdate as created_date,
        lastmodifieddate as last_modified_date,
        cast(archived as boolean) as is_archived

    from source

)

select * from cleaned
