-- Cleaning only: no business logic.
-- Grain: One row per HubSpot engagement.
with source as (
    select * from {{ ref('bronze_hubspot__engagement') }}
),

cleaned as (

    select
        {{ clean_str('id') }} as engagement_id,
        {{ clean_str('type') }} as engagement_type,
        created_at as created_date,
        {{ clean_str('owner_id') }} as owner_id,
        {{ clean_str('associated_deal_id') }} as deal_id,
        {{ clean_str('associated_company_id') }} as company_id,
        {{ clean_str('body_preview') }} as body_preview

    from source

)

select * from cleaned
