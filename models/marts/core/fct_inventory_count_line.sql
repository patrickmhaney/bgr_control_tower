-- Grain: one row per counted stock position (SESNUM_0 + CNTLIN_0).
--
-- The atomic fact behind Inventory Accuracy. The point of this model - and the
-- reason the metric was blocked without it - is that a count session records
-- what was COUNTED, not only what changed. STOJOU adjustments give a
-- numerator with no denominator; this gives both.
--
-- system_qty is the theoretical quantity AT COUNT TIME. It cannot be
-- reconstructed later from dim/fct stock, so if this table is ever dropped
-- from the extract the metric cannot be rebuilt retrospectively. That is
-- called out in ingestion/config.py as well.
--
-- Accuracy is measured by POSITION, not by unit. A site that miscounts one
-- pallet of 5,000 and gets 400 positions right is 99.75% accurate here and
-- would be far worse on a unit basis. Both are legitimate; the position basis
-- is the common warehouse convention and it is stated rather than assumed.

{% set tol = var('inventory_accuracy_tolerance_pct') %}

with count_line as (

    select
        count_session_number,
        count_line_number,
        item_code,
        site_code,
        location_code,
        lot_code,
        system_qty,
        counted_qty,
        count_line_status

    from {{ ref('stg_sage_x3__stocountd') }}

),

count_session as (

    select
        count_session_number,
        count_date,
        count_type,
        session_status,
        counted_by

    from {{ ref('stg_sage_x3__stocount') }}

),

joined as (

    select
        count_line.*,
        count_session.count_date,
        count_session.count_type,
        count_session.session_status,
        count_session.counted_by

    from count_line
    inner join count_session using (count_session_number)

),

final as (

    select
        count_session_number,
        count_line_number,

        -- Conformed dimension keys
        cast(strftime(count_date, '%Y%m%d') as integer)      as count_date_key,
        coalesce(item_code, 'UNKNOWN')                       as item_code,
        coalesce(site_code, 'UNKNOWN')                       as site_code,

        -- Degenerate attributes
        location_code,
        lot_code,
        count_type,
        session_status,
        counted_by,

        -- Dates
        count_date,

        -- Measures
        system_qty,
        counted_qty,
        counted_qty - system_qty                             as variance_qty,
        abs(counted_qty - system_qty)                        as absolute_variance_qty,
        case when system_qty = 0 then null
             else cast(abs(counted_qty - system_qty) / system_qty * 100
                       as decimal(18, 4))
        end                                                  as variance_pct,

        -- Flags. A position with a zero system quantity that counts zero is
        -- accurate; one that counts anything is not. The percentage form
        -- cannot express that, so the flag is computed on the absolute
        -- variance and falls back to the percentage only when there is a
        -- denominator to divide by.
        case
            when {{ tol }} = 0 then counted_qty = system_qty
            when system_qty = 0 then counted_qty = 0
            else abs(counted_qty - system_qty) / system_qty * 100 <= {{ tol }}
        end                                                  as is_accurate_position,
        counted_qty > system_qty                             as is_overage,
        counted_qty < system_qty                             as is_shortage

    from joined

)

select * from final
