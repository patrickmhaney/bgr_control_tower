{{ config(materialized='table') }}

-- Grain: one row per document currency and calendar month.
--
-- There is no FX rate table in any source system. The only rate signal in the
-- estate is implied by the X3 GL, which posts every line in both document
-- currency (AMTCUR_0) and company currency (AMTLOC_0). Dividing one by the
-- other recovers the rate that was actually applied at posting time, which is
-- the rate the financial statements already agree with.
--
-- Today this returns a constant 0.74 for CAD. The model is shaped as a monthly
-- series anyway, because the day a real rate feed arrives the shape should not
-- have to change - only the source. See open question 10.

with gl_line as (

    select
        header.currency_code,
        header.accounting_date,
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
        date_trunc('month', accounting_date) as rate_month,
        -- Volume-weighted, not a mean of ratios: a mean of ratios lets a
        -- single tiny line move the rate as much as a large one.
        sum(amount_company_currency) / sum(amount_document_currency) as rate_to_company_currency,
        count(*) as gl_line_count

    from gl_line
    group by 1, 2

),

currency_default as (

    -- Fallback for months the GL does not cover. Without this, any fact dated
    -- outside the GL's range silently loses its converted amount.
    select
        currency_code,
        sum(amount_company_currency) / sum(amount_document_currency) as rate_to_company_currency

    from gl_line
    group by 1

),

final as (

    select
        monthly.currency_code,
        monthly.rate_month,
        cast(monthly.rate_to_company_currency as decimal(18, 6)) as rate_to_reporting_currency,
        cast(currency_default.rate_to_company_currency as decimal(18, 6)) as fallback_rate,
        monthly.gl_line_count,
        '{{ var("reporting_currency") }}' as reporting_currency,
        'derived_from_x3_gl' as rate_source

    from monthly
    inner join currency_default using (currency_code)

)

select * from final
