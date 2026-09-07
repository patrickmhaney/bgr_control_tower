-- Invoiced revenue must reconcile to GL account 41000.
--
-- Not to the cent: the two sides take different rounding paths. fct_invoice_line
-- converts each line with decimal(18,6) rate x decimal(18,4) amount, while the
-- GL carries an amount already converted at posting. The residual is $0.09
-- across 218.9M - about four parts per billion - and it is FX rounding, not a
-- modelling gap.
--
-- Tolerance is $1.00: comfortably above the measured residual, comfortably
-- below anything that would represent a real difference. If this starts
-- failing, look for a line excluded by a join rather than for more rounding.
--
-- This is the one figure in the deck a CFO will check, which is why it is a
-- test rather than a sentence.

with invoiced as (
    select sum(line_net_amount_usd) as amount
    from {{ ref('fct_invoice_line') }}
),

gl_revenue as (
    select sum(amount_company_currency) as amount
    from {{ ref('stg_sage_x3__gaccentryd') }}
    where gl_account_code = '41000'
)

select
    invoiced.amount as invoiced_amount,
    gl_revenue.amount as gl_amount,
    invoiced.amount - gl_revenue.amount as difference

from invoiced
cross join gl_revenue
where abs(invoiced.amount - gl_revenue.amount) > 1.00
