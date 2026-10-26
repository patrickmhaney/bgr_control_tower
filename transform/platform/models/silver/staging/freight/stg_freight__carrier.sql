-- Cleaning only: no business logic.
-- Grain: One row per carrier.
with source as (
    select * from {{ ref('bronze_freight__carrier') }}
),

cleaned as (

    select
        upper({{ clean_str('carrier_code') }}) as carrier_code,
        {{ clean_str('carrier_name') }} as carrier_name,
        lower({{ clean_str('mode') }}) as transport_mode

    from source

)

select * from cleaned
