-- Grain: one row per sales order line (SOHNUM_0 + SOPLIN_0). 11,575 rows.
--
-- The atomic O2C fact. Amounts are carried in both document currency and the
-- reporting currency, suffixed _doc and _usd, because the estate is genuinely
-- multi-currency (3,512 USD and 688 CAD orders) and a single unlabelled
-- "amount" column on a multi-currency fact is how two dashboards end up
-- disagreeing about revenue.
--
-- Returns are folded in here as columns rather than published as their own
-- fact for Return Rate to divide across. A ratio whose numerator and
-- denominator come from two different facts cannot be filtered coherently -
-- slice it by item and the two sides answer different questions. Carrying
-- returned_amount_usd on the order line makes the metric a plain sum/sum on
-- one grain, which is additive, re-aggregation-safe, and sliceable by every
-- dimension the line already has.

with order_line as (

    select
        sales_order_number,
        sales_order_line_number,
        item_code,
        shipping_site_code,
        ordered_qty,
        shipped_qty,
        requested_delivery_date,
        unit_of_measure,
        item_description_at_order,
        gross_unit_price,
        net_unit_price,
        discount_amount,
        line_net_amount

    from {{ ref('int_sales_order_line') }}

),

order_header as (

    select
        sales_order_number,
        sales_site_code,
        ordering_customer_code,
        invoicing_customer_code,
        order_date,
        shipment_date,
        currency_code,
        order_status,
        primary_rep_code,
        invoicing_status_code

    from {{ ref('stg_sage_x3__sorder') }}

),

fx as (

    select
        currency_code,
        rate_month,
        rate_to_reporting_currency,
        fallback_rate

    from {{ ref('int_fx_rate') }}

),

-- Returns matched back to the order line. A line can be returned more than
-- once (partial returns on separate dates), so this aggregates. Orphan
-- returns - the 8% whose order reference resolves to nothing - are absent
-- here by construction and are counted instead by the return coverage check
-- in the intermediate model.
-- What was actually invoiced against the line. Return Rate divides by this
-- rather than by the ordered amount: a line can be ordered and never invoiced,
-- and including it in the denominator dilutes the rate with value that was
-- never at risk of being returned. Credit memos are excluded here - they carry
-- no order reference by construction, and they ARE the returns.
invoiced as (

    select
        line.sales_order_number,
        line.sales_order_line_number,
        sum(line.line_net_amount)   as invoiced_amount,
        count(*)                    as invoice_line_count

    from {{ ref('stg_sage_x3__sinvoiced') }} as line
    inner join {{ ref('stg_sage_x3__sinvoicev') }} as header
        on header.invoice_number = line.invoice_number
    where line.sales_order_number is not null
      and header.invoice_type_code = 'SIN'
    group by 1, 2

),

returns as (

    select
        sales_order_number,
        sales_order_line_number,
        sum(returned_qty)       as returned_qty,
        sum(line_net_amount)    as returned_amount,
        min(return_date)        as first_return_date,
        count(*)                as return_line_count

    from {{ ref('int_sales_return_line') }}
    where sales_order_number is not null
    group by 1, 2

),

joined as (

    select
        order_line.*,
        order_header.sales_site_code,
        order_header.ordering_customer_code,
        order_header.invoicing_customer_code,
        order_header.order_date,
        order_header.shipment_date,
        order_header.currency_code,
        order_header.order_status,
        order_header.primary_rep_code,
        order_header.invoicing_status_code,
        coalesce(fx.rate_to_reporting_currency, fx_default.fallback_rate, 1.0) as fx_rate,
        fx.rate_to_reporting_currency is null                                  as fx_rate_is_fallback,
        coalesce(invoiced.invoiced_amount, 0)                                  as invoiced_amount,
        coalesce(invoiced.invoice_line_count, 0)                               as invoice_line_count,
        coalesce(returns.returned_qty, 0)                                      as returned_qty,
        coalesce(returns.returned_amount, 0)                                   as returned_amount,
        returns.first_return_date,
        coalesce(returns.return_line_count, 0)                                 as return_line_count

    from order_line
    inner join order_header using (sales_order_number)
    left join invoiced
        using (sales_order_number, sales_order_line_number)
    left join returns
        using (sales_order_number, sales_order_line_number)
    left join fx
        on fx.currency_code = order_header.currency_code
        and fx.rate_month = date_trunc('month', order_header.order_date)
    left join (select distinct currency_code, fallback_rate from fx) as fx_default
        on fx_default.currency_code = order_header.currency_code

),

final as (

    select
        joined.sales_order_number,
        joined.sales_order_line_number,

        -- Conformed dimension keys
        cast(strftime(joined.order_date, '%Y%m%d') as integer)  as order_date_key,
        cast(strftime(joined.requested_delivery_date, '%Y%m%d') as integer)
                                                                as requested_delivery_date_key,
        coalesce('X3-' || joined.ordering_customer_code, 'UNKNOWN') as customer_key,
        joined.ordering_customer_code                           as customer_code,
        joined.invoicing_customer_code,
        coalesce(joined.item_code, 'UNKNOWN')                   as item_code,
        coalesce(joined.shipping_site_code, 'UNKNOWN')          as site_code,
        joined.sales_site_code,
        joined.primary_rep_code,

        -- Degenerate attributes
        joined.order_status,
        joined.unit_of_measure,
        joined.item_description_at_order,
        joined.currency_code                                    as document_currency_code,

        -- Dates
        joined.order_date,
        joined.requested_delivery_date,
        joined.shipment_date,

        -- Measures: quantity
        joined.ordered_qty,
        joined.shipped_qty,
        joined.ordered_qty - joined.shipped_qty                 as open_qty,
        joined.returned_qty,

        -- Measures: money, document currency
        joined.gross_unit_price                                 as gross_unit_price_doc,
        joined.net_unit_price                                   as net_unit_price_doc,
        joined.discount_amount                                  as discount_amount_doc,
        joined.line_net_amount                                  as line_net_amount_doc,

        -- Measures: money, reporting currency
        cast(joined.line_net_amount * joined.fx_rate as decimal(18, 4))   as line_net_amount_usd,
        cast(joined.discount_amount * joined.fx_rate as decimal(18, 4))   as discount_amount_usd,
        cast(joined.invoiced_amount * joined.fx_rate as decimal(18, 4))   as invoiced_amount_usd,
        cast(joined.returned_amount * joined.fx_rate as decimal(18, 4))   as returned_amount_usd,
        cast(joined.fx_rate as decimal(18, 6))                            as fx_rate,
        joined.fx_rate_is_fallback,

        -- Flags
        joined.shipped_qty >= joined.ordered_qty                as is_fully_shipped,
        joined.shipment_date is null                            as has_no_shipment_date,
        joined.invoice_line_count > 0                           as is_invoiced,
        joined.return_line_count > 0                            as is_returned,
        joined.first_return_date

    from joined

)

select * from final
