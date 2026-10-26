-- Cleaning only: no business logic.
-- Grain: One row per HubSpot deal.
with source as (
    select * from {{ ref('bronze_hubspot__deal') }}
),

cleaned as (

    select
        {{ clean_str('id') }} as deal_id,
        {{ clean_str('dealname') }} as deal_name,
        try_cast({{ clean_str('amount') }} as double) as deal_amount,
        {{ clean_str('dealstage') }} as deal_stage_id,
        {{ clean_str('pipeline') }} as pipeline_id,
        closedate as close_date,
        createdate as created_date,
        hs_lastmodifieddate as last_modified_date,
        {{ clean_str('hubspot_owner_id') }} as owner_id,
        {{ clean_str('dealtype') }} as deal_type,
        cast(hs_is_closed_won as boolean) as is_closed_won,
        try_cast({{ clean_str('hs_deal_stage_probability') }} as double) as stage_probability,
        {{ clean_str('erp_order_number') }} as erp_order_number_raw,
        {{ clean_str('associated_company_id') }} as company_id,
        cast(archived as boolean) as is_archived

    from source

)

select * from cleaned
