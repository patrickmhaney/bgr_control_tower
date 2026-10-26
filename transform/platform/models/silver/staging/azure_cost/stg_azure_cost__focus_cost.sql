-- Cleaning only: no business logic.
-- Grain: One row per Azure resource per day.
with source as (
    select * from {{ ref('bronze_azure_cost__focus_cost') }}
),

cleaned as (

    select
        cast(ChargePeriodStart as date) as charge_date,
        {{ clean_str('ResourceName') }} as resource_name,
        {{ clean_str('ResourceType') }} as resource_type,
        {{ clean_str('ServiceCategory') }} as service_category,
        cast(BilledCost as decimal(18, 4)) as billed_cost,
        cast(EffectiveCost as decimal(18, 4)) as effective_cost,
        {{ clean_str('BillingCurrency') }} as billing_currency,
        {{ clean_str('x_Component') }} as component,
        {{ clean_str('x_Environment') }} as environment

    from source

)

select * from cleaned
