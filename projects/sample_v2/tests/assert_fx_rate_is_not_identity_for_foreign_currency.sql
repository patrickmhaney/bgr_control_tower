-- A non-reporting currency whose derived rate is exactly 1.0 means the GL is
-- posting AMTLOC_0 in the document currency rather than the reporting
-- currency -- which makes the derived rate meaningless rather than merely
-- imprecise.
--
-- int_fx_rate computes sum(AMTLOC_0) / sum(AMTCUR_0) across the whole GL with
-- no company filter, so it recovers a document-to-*company*-currency rate and
-- publishes it as rate_to_reporting_currency. Those agree only when every
-- posting entity's local currency is the reporting currency. In this extract
-- they do: GLBCA posts AMTLOC_0 in USD at 0.74. That is unusual for a Canadian
-- legal entity, and the mock's COMPANY table carries no currency column to
-- check it against -- so this test is the guard until COMPANY.CUR_0 arrives
-- with the real folder. See open question 10.
--
-- If this fails, do not adjust the tolerance. It means 26.4M of CAD revenue is
-- reporting as USD.

select
    currency_code,
    rate_month,
    rate_to_reporting_currency

from {{ ref('int_fx_rate') }}
where currency_code <> '{{ var("reporting_currency") }}'
  and rate_to_reporting_currency = 1.0
