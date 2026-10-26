-- Grain: one row per source person record (X3 user, X3 rep, HubSpot owner).

select
    source_system,
    source_key,
    golden_key as employee_key,
    match_score,
    match_rule,
    steward_status
from {{ source('mdm', 'mdm_xref') }}
where domain = 'employee'
