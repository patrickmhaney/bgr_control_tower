-- Grain: one row per golden customer (MDM contract C3).
--
-- Survivorship, assumed (open question 7): X3 wins financial attributes
-- (group, payment terms, currency, credit limit, rep); HubSpot wins
-- firmographics (industry, size, domain). CRM companies with no ERP
-- counterpart stay in the dimension as crm_only: dropping them would make the
-- unmatched rate look like zero, which is exactly the number to see.

with golden as (

    select * from {{ source('mdm', 'mdm_golden_customer') }}

),

x3 as (

    select * from {{ ref('stg_sage_x3__bpcustomer') }}

),

crm_members as (

    -- Every HubSpot company merged into each golden record.
    select
        xref.customer_key,
        count(*) as crm_company_count,
        min(company.created_date) as first_crm_date,
        max(company.industry) as industry,
        max(company.employee_count) as employee_count,
        max(company.domain) as domain,
        max(case when company.country = 'Canada' then 'CAN' else 'USA' end) as crm_country_code,
        min(case when company.is_archived = true then 1 else 0 end) as all_archived,
        max(xref.match_score) as best_match_score,
        max(xref.match_rule) as match_rule,
        max(case when xref.steward_status = 'needs_review' then 1 else 0 end) as needs_review
    from {{ ref('conf_customer_xref') }} as xref
    inner join {{ ref('stg_hubspot__company') }} as company
        on xref.source_system = 'hubspot' and company.company_id = xref.source_key
    group by xref.customer_key

),

rep as (

    select rep_code, rep_name from {{ ref('stg_sage_x3__represent') }}

)

select
    cast(g.golden_key as varchar) as customer_key,
    cast(g.golden_name as varchar) as customer_name,
    cast(g.x3_customer_code as varchar) as x3_customer_code,
    cast(g.hubspot_company_id as varchar) as hubspot_company_id,
    cast(g.source_scope as varchar) as source_scope,
    cast(c.match_rule as varchar) as match_rule,
    cast(c.best_match_score as double) as match_score,
    cast(coalesce(c.needs_review, 0) as integer) as needs_steward_review,
    cast(x3.customer_group_code as varchar) as customer_group_code,
    cast(x3.payment_term_code as varchar) as payment_term_code,
    cast(x3.currency_code as varchar) as currency_code,
    cast(x3.credit_limit_amount as decimal(18, 4)) as credit_limit_amount,
    cast(x3.primary_rep_code as varchar) as primary_rep_code,
    cast(rep.rep_name as varchar) as primary_rep_name,
    cast(c.industry as varchar) as industry,
    cast(c.employee_count as double) as employee_count,
    cast(c.domain as varchar) as domain,
    cast(coalesce(case when x3.currency_code = 'CAD' then 'CAN' when x3.currency_code is not null then 'USA' end,
                  c.crm_country_code) as varchar) as country_code,
    cast(coalesce(c.crm_company_count, 0) as integer) as crm_company_count,
    cast(case when g.source_scope = 'both' then coalesce(c.crm_company_count, 0) else 0 end as integer)
        as crm_matched_company_count,
    cast(case when x3.created_date is null then c.first_crm_date
              when c.first_crm_date is null then x3.created_date
              when x3.created_date < c.first_crm_date then x3.created_date
              else c.first_crm_date end as date) as first_seen_date
from golden as g
left join x3
    on x3.customer_code = g.x3_customer_code
left join crm_members as c
    on c.customer_key = g.golden_key
left join rep
    on rep.rep_code = x3.primary_rep_code

union all

select 'UNKNOWN', 'Unresolved', null, null, 'erp_only', null, null, 0, null, null, null, null,
       null, null, null, null, null, null, 0, 0, null
