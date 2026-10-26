-- Grain: one row per supplier. X3 is the master; Netstock adds its planning
-- lead time, which drifts from X3's and is worth seeing side by side.

select
    cast(s.supplier_code as varchar) as supplier_code,
    cast(s.supplier_name as varchar) as supplier_name,
    cast(s.payment_term_code as varchar) as payment_term_code,
    cast(s.lead_time_days as integer) as x3_lead_time_days,
    cast(n.lead_time_days as integer) as netstock_lead_time_days
from {{ ref('stg_sage_x3__bpsupplier') }} as s
left join {{ ref('stg_netstock__supplier') }} as n
    on n.supplier_code = s.supplier_code

union all

select 'UNKNOWN', 'Unresolved', null, null, null
