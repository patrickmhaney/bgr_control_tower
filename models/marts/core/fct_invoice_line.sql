-- Grain: one row per sales invoice line (NUM_0 + SIDLIN_0). 9,767 rows.
--
-- The fact behind the DSO proxy. days_to_pay is null - not zero, not a large
-- number - wherever PAYDAT_0 carried the 1753-01-01 sentinel, which is 13.8%
-- of invoices. That null is the whole reason the metric is a proxy: an
-- unguarded date_diff over the raw column returns a mean of -13,708 days, and
-- silently dropping the unpaid invoices is what makes days-to-pay flatter than
-- real DSO.

with invoice_line as (

    select
        invoice_number,
        invoice_line_number,
        item_code,
        item_description_at_invoice,
        invoiced_qty,
        net_unit_price,
        line_net_amount,
        sales_order_number,
        sales_order_line_number,
        shipping_site_code

    from {{ ref('stg_sage_x3__sinvoiced') }}

),

invoice_header as (

    select
        invoice_number,
        invoice_type_code,
        invoice_date,
        customer_code,
        sales_site_code,
        currency_code,
        invoice_status_code,
        payment_date,
        accounting_date,
        invoice_net_amount

    from {{ ref('stg_sage_x3__sinvoicev') }}

),

customer_terms as (

    select
        customer_code,
        payment_term_code

    from {{ ref('stg_sage_x3__bpcustomer') }}

),

fx as (

    select
        currency_code,
        rate_month,
        rate_to_reporting_currency,
        fallback_rate

    from {{ ref('int_fx_rate') }}

),

joined as (

    select
        invoice_line.*,
        invoice_header.invoice_type_code,
        invoice_header.invoice_date,
        invoice_header.customer_code,
        invoice_header.sales_site_code,
        invoice_header.currency_code,
        invoice_header.invoice_status_code,
        invoice_header.payment_date,
        invoice_header.accounting_date,
        invoice_header.invoice_net_amount as header_net_amount,
        customer_terms.payment_term_code,
        coalesce(fx.rate_to_reporting_currency, fx_default.fallback_rate, 1.0) as fx_rate,
        fx.rate_to_reporting_currency is null                                  as fx_rate_is_fallback

    from invoice_line
    inner join invoice_header using (invoice_number)
    left join customer_terms on customer_terms.customer_code = invoice_header.customer_code
    left join fx
        on fx.currency_code = invoice_header.currency_code
        and fx.rate_month = date_trunc('month', invoice_header.invoice_date)
    left join (select distinct currency_code, fallback_rate from fx) as fx_default
        on fx_default.currency_code = invoice_header.currency_code

),

final as (

    select
        joined.invoice_number,
        joined.invoice_line_number,

        -- Conformed dimension keys
        cast(strftime(joined.invoice_date, '%Y%m%d') as integer)  as invoice_date_key,
        cast(strftime(joined.payment_date, '%Y%m%d') as integer)  as payment_date_key,
        coalesce('X3-' || joined.customer_code, 'UNKNOWN')        as customer_key,
        joined.customer_code,
        coalesce(joined.item_code, 'UNKNOWN')                     as item_code,
        coalesce(joined.shipping_site_code, 'UNKNOWN')            as site_code,
        joined.sales_site_code,
        joined.sales_order_number,
        joined.sales_order_line_number,

        -- Degenerate attributes
        joined.invoice_type_code,
        joined.payment_term_code,
        joined.item_description_at_invoice,
        joined.currency_code                                      as document_currency_code,

        -- Dates
        joined.invoice_date,
        joined.payment_date,
        joined.accounting_date,

        -- Measures: quantity
        joined.invoiced_qty,

        -- Measures: money, document currency
        joined.net_unit_price                                     as net_unit_price_doc,
        joined.line_net_amount                                    as line_net_amount_doc,

        -- Measures: money, reporting currency
        cast(joined.line_net_amount * joined.fx_rate as decimal(18, 4)) as line_net_amount_usd,
        cast(joined.fx_rate as decimal(18, 6))                          as fx_rate,
        joined.fx_rate_is_fallback,

        -- Measures: settlement. Null, never zero, where unpaid.
        --
        -- Only one days-to-pay column, deliberately. date_diff already returns
        -- null when payment_date is null, so a plain `days_to_pay` would be
        -- identical on all 9,767 rows while its shorter name implied it
        -- included unsettled invoices - which is the exact distinction the DSO
        -- proxy turns on.
        joined.payment_date is not null                            as is_settled,
        joined.payment_date is null                                as is_unsettled,
        case
            when joined.payment_date is null then null
            else date_diff('day', joined.invoice_date, joined.payment_date)
        end                                                        as days_to_pay_settled_only

    from joined

)

select * from final
