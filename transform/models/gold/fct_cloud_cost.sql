-- Grain: one row per Azure resource per day.
-- The platform's own running cost, by the component each resource implements
-- (its `component` tag). Licence costs are in the license_cost seed.

select
    cast(charge_date as date) as charge_date,
    cast(resource_name as varchar) as resource_name,
    cast(resource_type as varchar) as resource_type,
    cast(component as varchar) as component,
    cast(environment as varchar) as environment,
    cast(effective_cost as decimal(18, 4)) as cost_usd
from {{ ref('stg_azure_cost__focus_cost') }}
