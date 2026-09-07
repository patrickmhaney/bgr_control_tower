-- Grain: one row per sales order line (SOHNUM_0 + SOPLIN_0). 11,575 rows.
--
-- The atomic O2C fact. Amounts are carried in both document currency and the
-- reporting currency, suffixed _doc and _usd, because the estate is genuinely
-- multi-currency (3,512 USD and 688 CAD orders) and a single unlabelled
-- "amount" column on a multi-currency fact is how two dashboards end up
-- disagreeing about revenue.

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
        fx.rate_to_reporting_currency is null                                  as fx_rate_is_fallback

    from order_line
    inner join order_header using (sales_order_number)
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

        -- Measures: money, document currency
        joined.gross_unit_price                                 as gross_unit_price_doc,
        joined.net_unit_price                                   as net_unit_price_doc,
        joined.discount_amount                                  as discount_amount_doc,
        joined.line_net_amount                                  as line_net_amount_doc,

        -- Measures: money, reporting currency
        cast(joined.line_net_amount * joined.fx_rate as decimal(18, 4))   as line_net_amount_usd,
        cast(joined.discount_amount * joined.fx_rate as decimal(18, 4))   as discount_amount_usd,
        cast(joined.fx_rate as decimal(18, 6))                            as fx_rate,
        joined.fx_rate_is_fallback,

        -- Flags
        joined.shipped_qty >= joined.ordered_qty                as is_fully_shipped,
        joined.shipment_date is null                            as has_no_shipment_date

    from joined

)

select * from final
