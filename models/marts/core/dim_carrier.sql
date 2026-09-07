-- Grain: one row per carrier SCAC.

with carrier as (

    select
        carrier_scac,
        carrier_name,
        transport_mode

    from {{ ref('stg_pangea__carrier') }}

),

shipment_volume as (

    select
        carrier_scac,
        count(*)              as shipment_count,
        min(ship_date)        as first_shipment_date,
        max(ship_date)        as last_shipment_date

    from {{ ref('stg_pangea__shipment') }}
    group by 1

),

-- An UNKNOWN member, and every fact foreign key coalesced to it.
--
-- Without one, an unresolved key lands as null. `relationships` ignores nulls
-- so it still passes, `not_null` on the fact starts failing the build, and in
-- Power BI the rows collect on a blank dimension row that reads to a user as a
-- real member. With one, the existing tests keep passing and start meaning
-- "every fact is attributable", which is the assertion actually wanted.
--
-- Nothing is unresolved today. Customer resolution is 100% only because
-- pangea.shipment.customer_name happens to match all 220 distinct ERP names -
-- a coincidence open question 13 exists to check.

unknown_member as (

    select
        'UNKNOWN'                    as carrier_scac,
        'Unresolved'                 as carrier_name,
        cast(null as varchar)        as transport_mode,
        0                            as shipment_count,
        cast(null as date)           as first_shipment_date,
        cast(null as date)           as last_shipment_date,
        false                        as is_active_carrier

),

final as (

    select
        carrier.carrier_scac,
        carrier.carrier_name,
        carrier.transport_mode,
        coalesce(shipment_volume.shipment_count, 0) as shipment_count,
        shipment_volume.first_shipment_date,
        shipment_volume.last_shipment_date,
        shipment_volume.shipment_count is not null  as is_active_carrier

    from carrier
    left join shipment_volume on shipment_volume.carrier_scac = carrier.carrier_scac

)

select * from final
union all
select * from unknown_member
