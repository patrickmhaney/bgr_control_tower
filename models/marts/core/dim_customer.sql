-- Grain: one row per conformed customer.
--
-- Conformed across X3 and HubSpot, which have no shared key. The matching
-- itself lives in int_customer_xref and is deliberately not repeated here -
-- this model does one thing, which is apply the survivorship rule to whatever
-- the xref selected.
--
-- Survivorship (open question 7, assumed not confirmed):
--   X3 wins financial attributes - credit limit, payment terms, currency,
--   accounting code, sales rep. It is the system that bills.
--   HubSpot wins firmographics - industry, employee count, annual revenue,
--   domain. It is the system that researches.
--
-- Scope: the dimension holds three populations, and says which is which.
--   both      197 customers present in the ERP and matched to the CRM
--   erp_only   23 ERP customers the CRM has no record of
--   crm_only   31 CRM companies with no ERP match - prospects, or a
--              stewardship problem. The business needs to see this number.
--
-- The xref selects one ERP customer per CRM company, which does not guarantee
-- one CRM company per ERP customer: 32 CRM companies point at an ERP customer
-- another CRM company already claimed. The dimension is at ERP grain, so it
-- takes the highest-confidence claimant and publishes the collision count in
-- crm_candidate_count rather than fanning the dimension out.

with x3_customer as (

    select
        bpcustomer.customer_code,
        bpcustomer.customer_name,
        bpcustomer.customer_group_code,
        bpcustomer.currency_code,
        bpcustomer.payment_term_code,
        bpcustomer.credit_limit_amount,
        bpcustomer.accounting_code,
        bpcustomer.primary_rep_code,
        bpcustomer.secondary_rep_code,
        bpcustomer.created_date,
        bpartner.country_code

    from {{ ref('stg_sage_x3__bpcustomer') }} as bpcustomer
    left join {{ ref('stg_sage_x3__bpartner') }} as bpartner
        on bpartner.partner_code = bpcustomer.customer_code

),

hubspot_company as (

    select
        company_id,
        company_name,
        domain,
        industry,
        country,
        employee_count,
        annual_revenue,
        owner_id,
        created_date,
        is_archived

    from {{ ref('stg_hubspot__company') }}

),

selected_match as (

    select
        x3_customer_code,
        hubspot_company_id,
        match_method,
        confidence,
        is_ambiguous

    from {{ ref('int_customer_xref') }}
    where is_selected

),

surviving_match as (

    -- One CRM company per ERP customer. Highest confidence wins; the count of
    -- competing claimants is published rather than discarded.
    select
        x3_customer_code,
        arg_max(hubspot_company_id, confidence) as hubspot_company_id,
        arg_max(match_method, confidence)       as match_method,
        max(confidence)                         as confidence,
        bool_or(is_ambiguous)                   as is_ambiguous,
        count(*)                                as crm_candidate_count

    from selected_match
    group by 1

),

rep as (

    select
        rep_code,
        rep_name,
        site_code as rep_site_code

    from {{ ref('stg_sage_x3__represent') }}

),

erp_backed as (

    -- X3 is the spine wherever it has a row: these are the customers that can
    -- appear on a financial fact.
    select
        'X3-' || x3_customer.customer_code              as customer_key,
        x3_customer.customer_code,
        surviving_match.hubspot_company_id,

        -- X3 wins identity for anything that will be invoiced.
        x3_customer.customer_name                       as customer_name,
        hubspot_company.company_name                    as crm_company_name,

        -- X3: financial
        x3_customer.customer_group_code,
        x3_customer.currency_code,
        x3_customer.payment_term_code,
        x3_customer.credit_limit_amount,
        x3_customer.accounting_code,
        x3_customer.primary_rep_code,
        rep.rep_name                                    as primary_rep_name,
        x3_customer.secondary_rep_code,
        x3_customer.country_code,
        x3_customer.created_date                        as erp_created_date,

        -- HubSpot: firmographic
        hubspot_company.domain,
        hubspot_company.industry,
        hubspot_company.employee_count,
        hubspot_company.annual_revenue,
        hubspot_company.country                         as crm_country,
        hubspot_company.created_date                    as crm_created_date,
        coalesce(hubspot_company.is_archived, false)    as crm_is_archived,

        case when surviving_match.hubspot_company_id is not null
             then 'both' else 'erp_only' end            as source_scope,
        surviving_match.match_method,
        surviving_match.confidence                      as match_confidence,
        coalesce(surviving_match.is_ambiguous, false)   as match_is_ambiguous,
        coalesce(surviving_match.crm_candidate_count, 0) as crm_candidate_count,
        -- How many CRM companies this row accounts for. Summing it across the
        -- dimension recovers the CRM company count (260), which an ERP-grain
        -- row count cannot: 32 CRM companies lost a collision and would
        -- otherwise vanish from the denominator of any CRM coverage measure.
        coalesce(surviving_match.crm_candidate_count, 0) as crm_company_count

    from x3_customer
    left join surviving_match
        on surviving_match.x3_customer_code = x3_customer.customer_code
    left join hubspot_company
        on hubspot_company.company_id = surviving_match.hubspot_company_id
    left join rep
        on rep.rep_code = x3_customer.primary_rep_code

),

crm_only as (

    -- CRM companies with no selected ERP match. Kept in the dimension rather
    -- than dropped: an unmatched prospect is a real entity, and hiding it
    -- makes the 31 look like zero.
    select
        'HS-' || hubspot_company.company_id             as customer_key,
        cast(null as varchar)                           as customer_code,
        hubspot_company.company_id                      as hubspot_company_id,

        hubspot_company.company_name                    as customer_name,
        hubspot_company.company_name                    as crm_company_name,

        cast(null as varchar)                           as customer_group_code,
        cast(null as varchar)                           as currency_code,
        cast(null as varchar)                           as payment_term_code,
        cast(null as decimal(18, 4))                    as credit_limit_amount,
        cast(null as varchar)                           as accounting_code,
        cast(null as varchar)                           as primary_rep_code,
        cast(null as varchar)                           as primary_rep_name,
        cast(null as varchar)                           as secondary_rep_code,
        cast(null as varchar)                           as country_code,
        cast(null as date)                              as erp_created_date,

        hubspot_company.domain,
        hubspot_company.industry,
        hubspot_company.employee_count,
        hubspot_company.annual_revenue,
        hubspot_company.country                         as crm_country,
        hubspot_company.created_date                    as crm_created_date,
        hubspot_company.is_archived                     as crm_is_archived,

        'crm_only'                                      as source_scope,
        cast(null as varchar)                           as match_method,
        cast(null as decimal(4, 2))                     as match_confidence,
        false                                           as match_is_ambiguous,
        0                                               as crm_candidate_count,
        1                                               as crm_company_count

    from hubspot_company
    -- NOT EXISTS, not NOT IN. A single null in selected_match.hubspot_company_id
    -- makes a NOT IN predicate unknown for every row, so the CTE returns zero -
    -- deleting exactly the 31 unmatched CRM companies that
    -- customer_unmatched_rate exists to publish, and turning an 11.9%
    -- governance finding into 0% with a green build.
    where not exists (
        select 1
        from selected_match
        where selected_match.hubspot_company_id = hubspot_company.company_id
    )

),

-- An UNKNOWN member, and every fact foreign key coalesced to it.
--
-- Without one, an unresolved key lands as null. `relationships` ignores nulls
-- so it still passes, `not_null` on the fact starts failing the build, and in
-- Power BI the rows collect on a blank dimension row that reads to a user as a
-- real member. With one, the existing tests keep passing and start meaning
-- "every fact is attributable", which is the assertion actually wanted.
--
-- Nothing is unresolved today. Customer resolution is 100% only because
-- pangea.shipment.customer_name happens to match all 220 distinct ERP names -
-- a coincidence open question 13 exists to check.

unknown_member as (

    select
        'UNKNOWN'                                       as customer_key,
        cast(null as varchar)                           as customer_code,
        cast(null as varchar)                           as hubspot_company_id,
        'Unresolved'                                    as customer_name,
        cast(null as varchar)                           as crm_company_name,
        cast(null as varchar)                           as customer_group_code,
        cast(null as varchar)                           as currency_code,
        cast(null as varchar)                           as payment_term_code,
        cast(null as decimal(18, 4))                    as credit_limit_amount,
        cast(null as varchar)                           as accounting_code,
        cast(null as varchar)                           as primary_rep_code,
        cast(null as varchar)                           as primary_rep_name,
        cast(null as varchar)                           as secondary_rep_code,
        cast(null as varchar)                           as country_code,
        cast(null as date)                              as erp_created_date,
        cast(null as varchar)                           as domain,
        cast(null as varchar)                           as industry,
        cast(null as double)                            as employee_count,
        cast(null as double)                            as annual_revenue,
        cast(null as varchar)                           as crm_country,
        cast(null as date)                              as crm_created_date,
        false                                           as crm_is_archived,
        'unknown'                                       as source_scope,
        cast(null as varchar)                           as match_method,
        cast(null as decimal(4, 2))                     as match_confidence,
        false                                           as match_is_ambiguous,
        0                                               as crm_candidate_count,
        0                                               as crm_company_count

),

final as (

    select * from erp_backed
    union all
    select * from crm_only

)

select * from final
union all
select * from unknown_member
