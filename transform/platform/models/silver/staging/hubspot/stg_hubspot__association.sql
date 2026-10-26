-- Cleaning only: no business logic.
-- Grain: One row per HubSpot object association.
with source as (
    select * from {{ ref('bronze_hubspot__association') }}
),

cleaned as (

    select
        {{ clean_str('from_object_type') }} as from_object_type,
        {{ clean_str('from_id') }} as from_id,
        {{ clean_str('to_object_type') }} as to_object_type,
        {{ clean_str('to_id') }} as to_id,
        {{ clean_str('association_type') }} as association_type

    from source

)

select * from cleaned
