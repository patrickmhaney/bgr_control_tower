-- Grain: one row per shipment.
--
-- Collapses the charge lines to a shipment-level cost with the accessorial mix
-- preserved as separate columns, so "cost per shipment went up" can be
-- answered with "because detention doubled" without going back to the source.
--
-- README landmine 13 says shipment.total_cost_usd disagrees with the sum of
-- charges. Measured: not one of the 3,509 shipments agrees to the cent, only 30
-- agree within a dollar, and the header is 9.9% higher in aggregate. This model
-- computes both and the variance; which one a metric uses is
-- var('shipment_cost_basis').

with charge as (

    select
        shipment_id,
        charge_code,
        charge_amount_usd

    from {{ ref('stg_pangea__charge') }}

),

pivoted as (

    select
        shipment_id,
        sum(charge_amount_usd)                                                as charge_total_usd,
        sum(charge_amount_usd) filter (where charge_code = 'FREIGHT')         as freight_usd,
        sum(charge_amount_usd) filter (where charge_code = 'FUEL')            as fuel_surcharge_usd,
        sum(charge_amount_usd) filter (where charge_code not in ('FREIGHT', 'FUEL'))
                                                                              as accessorial_usd,
        sum(charge_amount_usd) filter (where charge_code = 'DETENTION')       as detention_usd,
        sum(charge_amount_usd) filter (where charge_code = 'LIFTGATE')        as liftgate_usd,
        sum(charge_amount_usd) filter (where charge_code = 'RESIDENTIAL')     as residential_usd,
        count(*)                                                              as charge_line_count

    from charge
    group by 1

),

final as (

    select
        shipment.shipment_id,
        coalesce(pivoted.charge_total_usd, 0)     as charge_total_usd,
        coalesce(pivoted.freight_usd, 0)          as freight_usd,
        coalesce(pivoted.fuel_surcharge_usd, 0)   as fuel_surcharge_usd,
        coalesce(pivoted.accessorial_usd, 0)      as accessorial_usd,
        coalesce(pivoted.detention_usd, 0)        as detention_usd,
        coalesce(pivoted.liftgate_usd, 0)         as liftgate_usd,
        coalesce(pivoted.residential_usd, 0)      as residential_usd,
        coalesce(pivoted.charge_line_count, 0)    as charge_line_count,
        shipment.header_cost_usd,
        coalesce(pivoted.charge_total_usd, 0) - shipment.header_cost_usd as cost_variance_usd

    from {{ ref('stg_pangea__shipment') }} as shipment
    left join pivoted on pivoted.shipment_id = shipment.shipment_id

)

select * from final
