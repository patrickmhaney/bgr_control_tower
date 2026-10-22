{% set tol = var('inventory_accuracy_tolerance_pct') %}

-- Grain: one row per counted stock position.
-- Feeds Inventory Accuracy. The system quantity is the one recorded at count
-- time, which cannot be recovered later. Tolerance is open question 15.

with count_line as (

    select * from {{ ref('stg_sage_x3__stocountd') }}

),

count_session as (

    select count_session_number, count_date, count_type, session_status, counted_by
    from {{ ref('stg_sage_x3__stocount') }}

),

joined as (

    select
        cl.*,
        cs.count_date,
        cs.count_type,
        cs.session_status,
        cs.counted_by
    from count_line as cl
    inner join count_session as cs
        on cs.count_session_number = cl.count_session_number

)

select
    cast(count_session_number as varchar) as count_session_number,
    cast(count_line_number as bigint) as count_line_number,
    cast(count_date as date) as count_date,
    cast(coalesce(item_code, 'UNKNOWN') as varchar) as item_code,
    cast(coalesce(site_code, 'UNKNOWN') as varchar) as site_code,
    cast({{ employee_key('counted_by') }} as varchar) as employee_key,
    cast(location_code as varchar) as location_code,
    cast(count_type as varchar) as count_type,
    cast(session_status as varchar) as session_status,
    cast(system_qty as decimal(18, 4)) as system_qty,
    cast(counted_qty as decimal(18, 4)) as counted_qty,
    cast(abs(counted_qty - system_qty) as decimal(18, 4)) as absolute_variance_qty,
    cast(case
            when {{ tol }} = 0 then {{ flag('counted_qty = system_qty') }}
            when system_qty = 0 then {{ flag('counted_qty = 0') }}
            else {{ flag('abs(counted_qty - system_qty) / system_qty * 100 <= ' ~ tol) }}
         end as integer) as is_accurate_position,
    cast(1 as integer) as count_line_count
from joined
