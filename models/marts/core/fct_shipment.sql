-- Grain: one row per shipment (pangea.shipment_id). 3,509 rows.
--
-- The atomic fact behind both computable I2D metrics. Two design decisions are
-- visible in the columns rather than buried in a filter:
--
-- 1. On-time is computed against BOTH promises and both flags are stored. The
--    two answers differ by 8.5 points (75.6% carrier, 84.1% customer) and the
--    business has not chosen. The metric definition names the basis column it
--    wants, so switching is an edit to one YAML file rather than a rebuild of
--    this model - and publishing both as two metrics is a two-line change.
--
-- 2. Cost is carried on both bases with the variance between them. The charge
--    lines are the default; the header is 9.9% higher in aggregate and agrees
--    with the lines on zero shipments.
--
-- Undelivered shipments (109 EXCEPTION, 19 IN_TRANSIT) keep a null on-time
-- flag rather than false. That is deliberate and it is a known weakness of the
-- metric as specified - see open question 1 - but encoding "we do not know" as
-- "on time = no" here would hide the decision instead of surfacing it.

with shipment as (

    select
        shipment_id,
        reference_number,
        customer_name,
        carrier_scac,
        service_level,
        transport_mode,
        origin_site_code,
        destination_city,
        destination_state,
        destination_postal_code,
        destination_country,
        ship_date,
        carrier_promised_delivery_date,
        delivered_date,
        shipment_status,
        weight_lb,
        piece_count,
        header_cost_usd

    from {{ ref('stg_pangea__shipment') }}

),

charge as (

    select
        shipment_id,
        charge_total_usd,
        freight_usd,
        fuel_surcharge_usd,
        accessorial_usd,
        detention_usd,
        liftgate_usd,
        residential_usd,
        charge_line_count,
        cost_variance_usd

    from {{ ref('int_shipment_charge') }}

),

milestone as (

    select
        shipment_id,
        picked_up_date,
        out_for_delivery_date,
        delivered_event_date,
        exception_date,
        transit_days,
        event_count,
        had_exception,
        out_of_sequence_event_count,
        has_out_of_sequence_events

    from {{ ref('int_shipment_milestone') }}

),

order_link as (

    select
        shipment_id,
        sales_order_number,
        customer_code,
        customer_requested_delivery_date,
        customer_resolution_method,
        has_order_reference,
        order_date,
        primary_rep_code

    from {{ ref('int_shipment_order') }}

),

joined as (

    select
        shipment.*,
        charge.charge_total_usd,
        charge.freight_usd,
        charge.fuel_surcharge_usd,
        charge.accessorial_usd,
        charge.detention_usd,
        charge.liftgate_usd,
        charge.residential_usd,
        charge.charge_line_count,
        charge.cost_variance_usd,
        milestone.picked_up_date,
        milestone.out_for_delivery_date,
        milestone.delivered_event_date,
        milestone.exception_date,
        milestone.transit_days,
        milestone.event_count,
        milestone.had_exception,
        milestone.out_of_sequence_event_count,
        milestone.has_out_of_sequence_events,
        order_link.sales_order_number,
        order_link.customer_code,
        order_link.customer_requested_delivery_date,
        order_link.customer_resolution_method,
        order_link.has_order_reference,
        order_link.order_date,
        order_link.primary_rep_code

    from shipment
    left join charge on charge.shipment_id = shipment.shipment_id
    left join milestone on milestone.shipment_id = shipment.shipment_id
    left join order_link on order_link.shipment_id = shipment.shipment_id

),

final as (

    select
        joined.shipment_id,

        -- Conformed dimension keys
        cast(strftime(joined.ship_date, '%Y%m%d') as integer)      as ship_date_key,
        cast(strftime(joined.delivered_date, '%Y%m%d') as integer) as delivered_date_key,
        coalesce('X3-' || joined.customer_code, 'UNKNOWN')         as customer_key,
        joined.customer_code,
        coalesce(joined.origin_site_code, 'UNKNOWN')               as site_code,
        coalesce(joined.carrier_scac, 'UNKNOWN')                   as carrier_scac,
        joined.sales_order_number,
        joined.primary_rep_code,

        -- Degenerate attributes
        joined.reference_number,
        joined.service_level,
        joined.transport_mode,
        joined.shipment_status,
        joined.destination_city,
        joined.destination_state,
        joined.destination_postal_code,
        joined.destination_country,
        joined.customer_resolution_method,
        joined.has_order_reference,

        -- Dates
        joined.ship_date,
        joined.picked_up_date,
        joined.carrier_promised_delivery_date,
        joined.customer_requested_delivery_date,
        joined.delivered_date,
        joined.order_date,

        -- Measures: volume
        joined.weight_lb,
        joined.piece_count,
        joined.transit_days,
        joined.event_count,

        -- Measures: cost. charge lines are the default basis.
        joined.charge_total_usd,
        joined.header_cost_usd,
        joined.cost_variance_usd,
        joined.freight_usd,
        joined.fuel_surcharge_usd,
        joined.accessorial_usd,
        joined.detention_usd,
        joined.liftgate_usd,
        joined.residential_usd,
        joined.charge_line_count,
        {% if var('shipment_cost_basis') == 'charge_lines' %}
        joined.charge_total_usd                                    as shipment_cost_usd,
        {% else %}
        joined.header_cost_usd                                     as shipment_cost_usd,
        {% endif %}
        '{{ var("shipment_cost_basis") }}'                         as shipment_cost_basis,

        -- Measures: on-time, both bases. Null where undelivered.
        joined.delivered_date is not null                          as is_delivered,
        case
            when joined.delivered_date is null then null
            else joined.delivered_date <= joined.carrier_promised_delivery_date
        end                                                        as is_on_time_vs_carrier_promise,
        case
            when joined.delivered_date is null then null
            when joined.customer_requested_delivery_date is null then null
            else joined.delivered_date <= joined.customer_requested_delivery_date
        end                                                        as is_on_time_vs_customer_request,
        -- No third, Jinja-selected `is_on_time` column. Storing both bases is
        -- the right call; selecting between them here made
        -- var('otd_promise_basis') a rebuild rather than the config change the
        -- docs describe, and it hid which basis a number came from. The metric
        -- definition names the basis column it wants, so switching is an edit
        -- to one YAML file - and publishing both as two metrics, which is the
        -- resolution open question 1 anticipates, is a two-line change.
        '{{ var("otd_promise_basis") }}'                           as otd_promise_basis,
        date_diff('day', joined.carrier_promised_delivery_date, joined.delivered_date)
                                                                   as days_late_vs_carrier_promise,
        date_diff('day', joined.customer_requested_delivery_date, joined.delivered_date)
                                                                   as days_late_vs_customer_request,

        -- Data quality flags, carried on the fact so they can be filtered in
        -- the dashboard rather than argued about in a meeting.
        joined.had_exception,
        joined.has_out_of_sequence_events,
        joined.out_of_sequence_event_count

    from joined

)

select * from final
