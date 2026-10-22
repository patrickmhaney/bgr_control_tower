-- Cleaning only: no business logic.
-- Grain: One row per deal stage change.
with source as (
    select * from {{ ref('bronze_hubspot__deal_stage_history') }}
),

cleaned as (

    select
        {{ clean_str('deal_id') }} as deal_id,
        {{ clean_str('stage') }} as deal_stage_id,
        changed_at as changed_at_date,
        {{ clean_str('changed_by_owner_id') }} as changed_by_owner_id

    from source

)

select * from cleaned
