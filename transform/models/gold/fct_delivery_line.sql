-- Grain: one row per delivery line - one shipment of one order line.
-- Feeds On-Time Delivery. A delivery counts toward the department of the
-- person who shipped it (decision D7). On time means delivered on or before
-- the date the customer requested on the order line; the promise basis is
-- open question 1.

with delivery_line as (

    select * from {{ ref('stg_sage_x3__sdeliveryd') }}

),

delivery as (

    select * from {{ ref('stg_sage_x3__sdelivery') }}

),

order_line as (

    select sales_order_number, sales_order_line_number, requested_delivery_date
    from {{ ref('stg_sage_x3__sorderq') }}

),

joined as (

    select
        dl.*,
        d.ship_date,
        d.delivered_date,
        d.customer_code,
        d.created_by,
        ol.requested_delivery_date
    from delivery_line as dl
    inner join delivery as d
        on d.delivery_number = dl.delivery_number
    left join order_line as ol
        on ol.sales_order_number = dl.sales_order_number
        and ol.sales_order_line_number = dl.sales_order_line_number

)

select
    cast(delivery_number as varchar) as delivery_number,
    cast(delivery_line_number as bigint) as delivery_line_number,
    cast(sales_order_number as varchar) as sales_order_number,
    cast(sales_order_line_number as bigint) as sales_order_line_number,
    cast(ship_date as date) as ship_date,
    cast(delivered_date as date) as delivered_date,
    cast(requested_delivery_date as date) as requested_delivery_date,
    cast({{ customer_key('sage_x3', 'customer_code') }} as varchar) as customer_key,
    cast(coalesce(item_code, 'UNKNOWN') as varchar) as item_code,
    cast(coalesce(shipping_site_code, 'UNKNOWN') as varchar) as site_code,
    cast({{ employee_key('created_by') }} as varchar) as employee_key,
    cast(delivered_qty as decimal(18, 4)) as delivered_qty,
    cast({{ flag('delivered_date is not null') }} as integer) as is_delivered,
    cast({{ flag('delivered_date is not null and delivered_date <= requested_delivery_date') }} as integer)
        as is_on_time,
    cast(case when delivered_date is null then null
              else {{ dbt.datediff('requested_delivery_date', 'delivered_date', 'day') }} end as integer)
        as days_late,
    cast(1 as integer) as delivery_line_count
from joined
