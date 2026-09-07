-- Grain: one row per shipment.
--
-- Milestone dates extracted from the tracking event stream by event_code.
--
-- 316 of 24,504 events (1.29%) carry a timestamp earlier than the previous
-- event by sequence, because carriers supply them that way. That makes
-- min(event_at) an unreliable pickup date and max(event_at) an unreliable
-- delivery date. Selecting on event_code is immune to the ordering problem;
-- where a code repeats, the event_seq breaks the tie, not the timestamp.

with event as (

    select
        shipment_id,
        event_sequence,
        event_code,
        event_at,
        event_location

    from {{ ref('stg_pangea__tracking_event') }}

),

first_by_code as (

    select
        shipment_id,
        event_code,
        arg_min(event_at, event_sequence)     as event_at,
        arg_min(event_location, event_sequence) as event_location,
        min(event_sequence)                     as event_sequence,
        count(*)                                as event_count

    from event
    group by 1, 2

),

pivoted as (

    select
        shipment_id,
        max(event_at) filter (where event_code = 'PU') as picked_up_date,
        max(event_at) filter (where event_code = 'DP') as departed_facility_date,
        max(event_at) filter (where event_code = 'AR') as arrived_facility_date,
        max(event_at) filter (where event_code = 'OD') as out_for_delivery_date,
        max(event_at) filter (where event_code = 'DL') as delivered_event_date,
        max(event_at) filter (where event_code = 'EX') as exception_date,
        max(event_location) filter (where event_code = 'DL') as delivery_location,
        sum(event_count) filter (where event_code = 'IT') as in_transit_scan_count,
        sum(event_count)                                  as event_count,
        bool_or(event_code = 'EX')                        as had_exception

    from first_by_code
    group by 1

),

sequence_integrity as (

    -- Published rather than fixed. A shipment whose scans arrived out of order
    -- is a shipment whose transit times should not be trusted, and the
    -- dashboard consumer is entitled to know which ones those are.
    select
        shipment_id,
        count(*) filter (
            where previous_event_date is not null and event_at < previous_event_date
        ) as out_of_sequence_event_count

    from (
        select
            shipment_id,
            event_at,
            lag(event_at) over (
                partition by shipment_id order by event_sequence
            ) as previous_event_date
        from event
    ) as ordered
    group by 1

),

final as (

    select
        pivoted.*,
        sequence_integrity.out_of_sequence_event_count,
        sequence_integrity.out_of_sequence_event_count > 0 as has_out_of_sequence_events,
        date_diff('day', pivoted.picked_up_date, pivoted.delivered_event_date) as transit_days

    from pivoted
    inner join sequence_integrity using (shipment_id)

)

select * from final
