-- Cleaning only: no business logic.
-- Grain: One row per pipeline and stage.
with source as (
    select * from {{ ref('bronze_hubspot__pipeline_stage') }}
),

cleaned as (

    select
        {{ clean_str('pipeline_id') }} as pipeline_id,
        {{ clean_str('pipeline_label') }} as pipeline_label,
        {{ clean_str('stage_id') }} as deal_stage_id,
        {{ clean_str('stage_label') }} as stage_label,
        cast(display_order as bigint) as display_order,
        cast(is_closed as boolean) as is_closed,
        cast(is_closed_won as boolean) as is_closed_won

    from source

)

select * from cleaned
