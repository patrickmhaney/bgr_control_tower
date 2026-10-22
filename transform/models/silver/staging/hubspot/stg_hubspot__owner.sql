-- Cleaning only: no business logic.
-- Grain: One row per HubSpot owner.
with source as (
    select * from {{ ref('bronze_hubspot__owner') }}
),

cleaned as (

    select
        {{ clean_str('id') }} as owner_id,
        lower({{ clean_str('email') }}) as email,
        {{ clean_str('first_name') }} as first_name,
        {{ clean_str('last_name') }} as last_name,
        {{ clean_str('user_id') }} as user_id,
        {{ clean_str('team_name') }} as team_name,
        cast(archived as boolean) as is_archived,
        created_at as created_date,
        updated_at as updated_date

    from source

)

select * from cleaned
