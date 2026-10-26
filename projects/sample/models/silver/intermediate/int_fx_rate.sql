{{ config(materialized='table') }}

-- Grain: one row per document currency and calendar month.
--
-- No source system has an FX rate table. The X3 GL posts every line in both
-- document currency (AMTCUR_0) and company currency (AMTLOC_0), so dividing
-- one by the other recovers the rate actually applied at posting - the rate the
-- financial statements already agree with. Volume-weighted, so one tiny line
-- cannot move the rate as much as a large one. See open question 10.

with gl_line as (

    select
        header.currency_code,
        {{ dbt.date_trunc('month', 'header.accounting_date') }} as rate_month,
        line.amount_document_currency,
        line.amount_company_currency
    from {{ ref('stg_sage_x3__gaccentryd') }} as line
    inner join {{ ref('stg_sage_x3__gaccentry') }} as header
        on line.journal_entry_number = header.journal_entry_number
    where line.amount_document_currency <> 0
      and header.accounting_date is not null

),

monthly as (

    select
        currency_code,
        rate_month,
        sum(amount_company_currency) / sum(amount_document_currency) as rate_to_company_currency
    from gl_line
    group by currency_code, rate_month

),

currency_default as (

    -- Fallback for months the GL does not cover, so a fact dated outside the
    -- GL's range does not silently lose its converted amount.
    select
        currency_code,
        sum(amount_company_currency) / sum(amount_document_currency) as fallback_rate
    from gl_line
    group by currency_code

)

select
    m.currency_code,
    cast(m.rate_month as date) as rate_month,
    cast(m.rate_to_company_currency as decimal(18, 6)) as rate_to_reporting_currency,
    cast(d.fallback_rate as decimal(18, 6)) as fallback_rate,
    '{{ var("reporting_currency") }}' as reporting_currency
from monthly as m
inner join currency_default as d
    on d.currency_code = m.currency_code
