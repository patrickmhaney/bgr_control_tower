-- Cleaning only: no business logic.
-- Grain: One row per shipment, each booked against one ERP delivery.
-- `reference` is the ERP delivery number as the carrier keyed it: a few arrive
-- lower case or without their SDH prefix. delivery_number puts both back.
with source as (
    select * from {{ ref('bronze_freight__shipment') }}
),

cleaned as (

    select
        {{ clean_str('shipment_id') }} as shipment_id,
        {{ clean_str('reference') }} as reference,
        case
            when upper({{ clean_str('reference') }}) like 'SDH%' then upper({{ clean_str('reference') }})
            else {{ dbt.concat(["'SDH'", "upper(" ~ clean_str('reference') ~ ")"]) }}
        end as delivery_number,
        upper({{ clean_str('carrier_code') }}) as carrier_code,
        {{ clean_str('origin_location') }} as origin_location,
        cast(ship_date as date) as ship_date,
        cast(delivered_date as date) as delivered_date,
        lower({{ clean_str('status') }}) as shipment_status,
        cast(weight_kg as decimal(18, 2)) as weight_kg

    from source

)

select * from cleaned
