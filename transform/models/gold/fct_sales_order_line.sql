-- Grain: one row per sales order line.
-- Feeds Return Rate and Order Fill Rate. The person who keyed the order is
-- the employee, so the order counts toward their department (decision D7).

with order_line as (

    select * from {{ ref('int_sales_order_line') }}

),

order_header as (

    select * from {{ ref('stg_sage_x3__sorder') }}

),

delivered as (

    select sales_order_number, sales_order_line_number,
           sum(delivered_qty) as delivered_qty
    from {{ ref('stg_sage_x3__sdeliveryd') }}
    group by sales_order_number, sales_order_line_number

),

invoiced as (

    select line.sales_order_number, line.sales_order_line_number,
           sum(line.line_net_amount) as invoiced_amount
    from {{ ref('stg_sage_x3__sinvoiced') }} as line
    inner join {{ ref('stg_sage_x3__sinvoicev') }} as header
        on header.invoice_number = line.invoice_number
    where header.invoice_type_code = 'SIN'
    group by line.sales_order_number, line.sales_order_line_number

),

returned as (

    select sales_order_number, sales_order_line_number,
           sum(line_net_amount) as returned_amount
    from {{ ref('int_sales_return_line') }}
    where sales_order_number is not null
    group by sales_order_number, sales_order_line_number

),

joined as (

    select
        l.*,
        h.ordering_customer_code,
        h.order_date,
        h.order_status,
        h.order_status_code,
        h.currency_code,
        h.primary_rep_code,
        h.created_by,
        coalesce(d.delivered_qty, 0) as delivered_qty,
        coalesce(i.invoiced_amount, 0) as invoiced_amount,
        coalesce(r.returned_amount, 0) as returned_amount
    from order_line as l
    inner join order_header as h
        on h.sales_order_number = l.sales_order_number
    left join delivered as d
        on d.sales_order_number = l.sales_order_number
        and d.sales_order_line_number = l.sales_order_line_number
    left join invoiced as i
        on i.sales_order_number = l.sales_order_number
        and i.sales_order_line_number = l.sales_order_line_number
    left join returned as r
        on r.sales_order_number = l.sales_order_number
        and r.sales_order_line_number = l.sales_order_line_number

)

select
    cast(sales_order_number as varchar) as sales_order_number,
    cast(sales_order_line_number as bigint) as sales_order_line_number,
    cast(order_date as date) as order_date,
    cast(requested_delivery_date as date) as requested_delivery_date,
    cast({{ customer_key('sage_x3', 'ordering_customer_code') }} as varchar) as customer_key,
    cast(coalesce(item_code, 'UNKNOWN') as varchar) as item_code,
    cast(coalesce(shipping_site_code, 'UNKNOWN') as varchar) as site_code,
    cast({{ employee_key('created_by') }} as varchar) as employee_key,
    cast(primary_rep_code as varchar) as rep_code,
    cast(order_status as varchar) as order_status,
    cast(currency_code as varchar) as document_currency_code,
    cast(ordered_qty as decimal(18, 4)) as ordered_qty,
    cast(delivered_qty as decimal(18, 4)) as delivered_qty,
    cast(line_net_amount as decimal(18, 4)) as line_net_amount_doc,
    cast({{ to_usd('line_net_amount', 'currency_code', 'order_date') }} as decimal(18, 4)) as line_net_amount_usd,
    cast({{ to_usd('invoiced_amount', 'currency_code', 'order_date') }} as decimal(18, 4)) as invoiced_amount_usd,
    cast({{ to_usd('returned_amount', 'currency_code', 'order_date') }} as decimal(18, 4)) as returned_amount_usd,
    cast({{ flag('invoiced_amount <> 0') }} as integer) as is_invoiced,
    cast({{ flag('returned_amount <> 0') }} as integer) as is_returned,
    cast({{ flag('delivered_qty >= ordered_qty') }} as integer) as is_fully_delivered,
    cast({{ flag('order_status_code = 3') }} as integer) as is_cancelled,
    cast(1 as integer) as order_line_count
from joined
