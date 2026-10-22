-- Grain: one row per HubSpot deal, as it stands today.
-- Feeds Win Rate, Pipeline Value and Sales Cycle Days. The owner is the
-- employee and the company is the customer, both resolved through MDM.

with deal as (

    select * from {{ ref('stg_hubspot__deal') }}

),

stage as (

    select deal_stage_id, pipeline_id, stage_label, is_closed, is_closed_won
    from {{ ref('stg_hubspot__pipeline_stage') }}

),

joined as (

    select
        deal.*,
        stage.stage_label,
        case when stage.is_closed = true then 1 else 0 end as closed,
        case when stage.is_closed_won = true then 1 else 0 end as won
    from deal
    left join stage
        on stage.deal_stage_id = deal.deal_stage_id
        and stage.pipeline_id = deal.pipeline_id
    where deal.is_archived = false

)

select
    cast(deal_id as varchar) as deal_id,
    cast(created_date as date) as created_date,
    cast(case when closed = 1 then close_date end as date) as close_date,
    cast(case when closed = 0 then close_date end as date) as expected_close_date,
    cast({{ customer_key('hubspot', 'company_id') }} as varchar) as customer_key,
    cast({{ employee_key('owner_id', source_system='hubspot') }} as varchar) as employee_key,
    cast(pipeline_id as varchar) as pipeline_id,
    cast(deal_stage_id as varchar) as deal_stage_id,
    cast(stage_label as varchar) as deal_stage,
    cast(deal_type as varchar) as deal_type,
    cast(deal_amount as decimal(18, 4)) as deal_amount_usd,
    cast(case when closed = 0 then deal_amount else 0 end as decimal(18, 4)) as open_amount_usd,
    cast(1 - closed as integer) as is_open,
    cast(closed as integer) as is_closed,
    cast(won as integer) as is_won,
    cast(closed - won as integer) as is_lost,
    cast(case when won = 1 then {{ dbt.datediff('created_date', 'close_date', 'day') }} end as integer)
        as days_to_win,
    cast(1 as integer) as deal_count
from joined
