{{ config(materialized='table') }}

-- Grain: one row per (HubSpot company, X3 customer) match candidate.
--
-- This model exists as a first-class artefact rather than as a join inside
-- dim_customer because the matching is uncertain and the business needs to see
-- the uncertainty. Every candidate pair is emitted with the method that found
-- it and a confidence score; nothing is discarded silently.
--
-- There is no shared key between HubSpot and X3. Four probes, in descending
-- precision. Two different counts are worth keeping apart, because they answer
-- different questions and a reader comparing them across documents otherwise
-- concludes one is wrong:
--
--   probe hits      every pair the probe fires on, before dedup
--   pairs credited  pairs whose STRONGEST probe was this one, after
--                   best_method_per_pair collapses them
--
-- The gap between the columns is what each tier actually adds over the tiers
-- above it, which is the number that matters when tuning.
--
--                                                        probe   pairs
--                                                         hits  credited
--   exact_name   0.95  upper(trim(name)) equality          171     171
--   alnum_name   0.90  punctuation and spacing ignored     183      12
--   domain_stem  0.75  HubSpot domain stem prefixes name   250      84
--   core_name    0.60  legal suffix stripped as well       310      43
--
-- core_name is deliberately last. It is the highest-recall probe and the only
-- one that generates genuine ambiguity - 71 companies match more than one X3
-- customer on core name alone, because "Redstone Machine Works LLC" and
-- "Redstone Machine Works Inc" are legally distinct entities with the same
-- core name. The domain stem retains the legal suffix's first characters and
-- resolves 62 of those 71.

-- depends_on: {{ ref('legal_suffix') }}
-- name_core() reads the suffix list from that seed through a macro, and
-- dbt cannot infer a ref() reached inside a conditional block.

with hubspot_company as (

    select
        company_id,
        company_name,
        domain,
        is_archived,
        {{ name_upper('company_name') }}  as name_upper,
        {{ name_alnum('company_name') }}  as name_alnum,
        {{ name_core('company_name') }}   as name_core,
        {{ domain_stem('domain') }}       as domain_stem

    from {{ ref('stg_hubspot__company') }}

),

x3_customer as (

    select
        customer_code,
        customer_name,
        {{ name_upper('customer_name') }} as name_upper,
        {{ name_alnum('customer_name') }} as name_alnum,
        {{ name_core('customer_name') }}  as name_core

    from {{ ref('stg_sage_x3__bpcustomer') }}

),

candidate as (

    select
        hubspot_company.company_id,
        x3_customer.customer_code,
        'exact_name' as match_method,
        0.95 as confidence
    from hubspot_company
    inner join x3_customer
        on hubspot_company.name_upper = x3_customer.name_upper

    union all

    select
        hubspot_company.company_id,
        x3_customer.customer_code,
        'alnum_name',
        0.90
    from hubspot_company
    inner join x3_customer
        on hubspot_company.name_alnum = x3_customer.name_alnum

    union all

    select
        hubspot_company.company_id,
        x3_customer.customer_code,
        'domain_stem',
        0.75
    from hubspot_company
    inner join x3_customer
        -- Below 12 characters the stem is short enough to prefix an unrelated
        -- company. Measured: at 12 the probe adds recall without adding ties.
        on length(hubspot_company.domain_stem) >= 12
        and starts_with(x3_customer.name_alnum, hubspot_company.domain_stem)

    union all

    select
        hubspot_company.company_id,
        x3_customer.customer_code,
        'core_name',
        0.60
    from hubspot_company
    inner join x3_customer
        on hubspot_company.name_core = x3_customer.name_core

),

best_method_per_pair as (

    -- A pair found by three probes is one candidate, credited to its strongest
    -- probe. Without this collapse the confidence ranking below would be
    -- decided by how many probes happened to fire, which is not evidence.
    select
        company_id,
        customer_code,
        max(confidence) as confidence,
        arg_max(match_method, confidence) as match_method,
        count(*) as probes_agreeing

    from candidate
    group by 1, 2

),

ranked as (

    select
        best_method_per_pair.*,
        row_number() over (
            partition by company_id
            order by confidence desc, probes_agreeing desc, customer_code
        ) as candidate_rank,
        count(*) over (
            partition by company_id, confidence
        ) as candidates_at_this_confidence

    from best_method_per_pair

),

final as (

    select
        {{ dbt_utils.generate_surrogate_key(['ranked.company_id', 'ranked.customer_code']) }} as customer_xref_key,
        ranked.company_id                                   as hubspot_company_id,
        hubspot_company.company_name                        as hubspot_company_name,
        hubspot_company.domain                              as hubspot_domain,
        hubspot_company.is_archived                         as hubspot_is_archived,
        ranked.customer_code                                as x3_customer_code,
        x3_customer.customer_name                           as x3_customer_name,
        ranked.match_method,
        cast(ranked.confidence as decimal(4, 2))            as confidence,
        ranked.probes_agreeing,
        ranked.candidate_rank,
        ranked.candidates_at_this_confidence > 1            as is_ambiguous,
        ranked.candidate_rank = 1                           as is_selected

    from ranked
    inner join hubspot_company on hubspot_company.company_id = ranked.company_id
    inner join x3_customer on x3_customer.customer_code = ranked.customer_code

)

select * from final
