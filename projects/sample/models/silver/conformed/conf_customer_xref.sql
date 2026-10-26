-- Grain: one row per source customer record (X3 customer or HubSpot company).
--
-- Reads contract C3 from whichever MDM provider ran. Every fact resolves its
-- customer through this table, so swapping the provider (or adopting an MDM
-- product) changes which golden record a source record lands on and nothing
-- else.

select
    source_system,
    source_key,
    golden_key as customer_key,
    match_score,
    match_rule,
    steward_status
from {{ source('mdm', 'mdm_xref') }}
where domain = 'customer'
