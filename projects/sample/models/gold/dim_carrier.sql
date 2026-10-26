-- Grain: one row per carrier, from the freight platform. UNKNOWN collects
-- deliveries no shipment was booked against.

select
    cast(carrier_code as varchar) as carrier_code,
    cast(carrier_name as varchar) as carrier_name,
    cast(transport_mode as varchar) as transport_mode
from {{ ref('stg_freight__carrier') }}

union all

select 'UNKNOWN', 'No shipment booked', null
