-- Grain: one row per shipment and event sequence (shipment_id + event_seq).
-- 24,504 rows.
--
-- The milestone-level fact. fct_shipment answers "was it on time"; this
-- answers "where did the time go". Kept atomic because collapsing it to
-- milestones is exactly what int_shipment_milestone already does, and throwing
-- away the intermediate scans would make transit-leg analysis impossible
-- later.
--
-- is_out_of_sequence is computed here rather than corrected. 1.29% of events
-- arrive with a timestamp earlier than the previous event by sequence; that is
-- the carrier's data and pretending otherwise would be inventing history.

with event as (

    select
        shipment_id,
        event_sequence,
        event_code,
        event_description,
        event_at,
        event_location

    from {{ ref('stg_pangea__tracking_event') }}

),

sequenced as (

    select
        event.*,
        lag(event_at) over (
            partition by shipment_id order by event_sequence
        ) as previous_event_date,
        first_value(event_at) over (
            partition by shipment_id order by event_sequence
        ) as first_event_date

    from event

),

shipment_context as (

    select
        shipment_id,
        customer_key,
        customer_code,
        site_code,
        carrier_scac,
        sales_order_number,
        service_level,
        transport_mode

    from {{ ref('fct_shipment') }}

),

final as (

    select
        sequenced.shipment_id,
        sequenced.event_sequence,

        coalesce(shipment_context.customer_key, 'UNKNOWN')        as customer_key,
        shipment_context.customer_code,
        coalesce(shipment_context.site_code, 'UNKNOWN')           as site_code,
        coalesce(shipment_context.carrier_scac, 'UNKNOWN')        as carrier_scac,
        shipment_context.sales_order_number,
        shipment_context.service_level,
        shipment_context.transport_mode,
        cast(strftime(sequenced.event_at, '%Y%m%d') as integer) as event_date_key,

        sequenced.event_code,
        sequenced.event_description,
        sequenced.event_at,
        sequenced.event_location,

        date_diff('day', sequenced.previous_event_date, sequenced.event_at) as days_since_previous_event,
        date_diff('day', sequenced.first_event_date, sequenced.event_at)    as days_since_first_event,

        sequenced.previous_event_date is not null
            and sequenced.event_at < sequenced.previous_event_date as is_out_of_sequence,
        sequenced.event_code = 'DL'                                  as is_delivery_event,
        sequenced.event_code = 'EX'                                  as is_exception_event

    from sequenced
    left join shipment_context using (shipment_id)

)

select * from final
