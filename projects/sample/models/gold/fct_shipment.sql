-- Grain: one row per shipment - one X3 delivery moved by one carrier.
-- Feeds Cost Per Shipment. A shipment's freight cost is the sum of its
-- carrier invoice (line haul, fuel surcharge, accessorials); until the invoice
-- arrives the shipment is not yet invoiced and stays out of the ratio.

with shipment as (

    select * from {{ ref('stg_freight__shipment') }}

),

invoice as (

    select
        shipment_id,
        max(invoice_date) as invoice_date,
        sum(line_haul_amount + fuel_surcharge_amount + accessorial_amount) as freight_cost
    from {{ ref('stg_freight__freight_invoice') }}
    group by shipment_id

),

delivery as (

    select delivery_number, shipping_site_code, customer_code
    from {{ ref('stg_sage_x3__sdelivery') }}

),

joined as (

    select
        s.shipment_id,
        s.delivery_number,
        s.carrier_code,
        s.ship_date,
        s.weight_kg,
        coalesce(d.shipping_site_code, s.origin_location) as site_code,
        d.customer_code,
        d.delivery_number as matched_delivery_number,
        i.invoice_date,
        i.freight_cost
    from shipment as s
    left join delivery as d
        on d.delivery_number = s.delivery_number
    left join invoice as i
        on i.shipment_id = s.shipment_id

)

select
    cast(shipment_id as varchar) as shipment_id,
    cast(delivery_number as varchar) as delivery_number,
    cast(ship_date as date) as ship_date,
    cast(invoice_date as date) as invoice_date,
    cast(coalesce(carrier_code, 'UNKNOWN') as varchar) as carrier_code,
    cast(coalesce(site_code, 'UNKNOWN') as varchar) as site_code,
    cast({{ platform.customer_key('sage_x3', 'customer_code') }} as varchar) as customer_key,
    cast(weight_kg as decimal(18, 2)) as weight_kg,
    cast(coalesce(freight_cost, 0) as decimal(18, 2)) as freight_cost_usd,
    cast({{ platform.flag('freight_cost is not null') }} as integer) as is_invoiced,
    cast({{ platform.flag('matched_delivery_number is not null') }} as integer) as is_matched_to_delivery,
    cast(1 as integer) as shipment_count
from joined
