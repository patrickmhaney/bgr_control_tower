-- Grain: one row per shipment.
--
-- Resolves a shipment to the X3 sales order and to the conformed customer.
-- Two probes, because the README's join map only documents the first and the
-- second is measurably better where the first fails:
--
--   order_reference  85.4% of shipments (2,998 of 3,509). The rest are 247
--                    nulls and 264 CUST-PO-##### customer POs that match
--                    nothing in X3.
--   customer_name    pangea.shipment.customer_name matches BPCUSTOMER.BPCNAM_0
--                    on all 220 distinct values. It cannot recover the order,
--                    but it recovers the customer, which is what most of the
--                    dimensional analysis actually needs.
--
-- The order reference is what On-Time Delivery needs when measured against the
-- customer request date, so the coverage gap is a metric-definition constraint
-- and not merely a data quality note. See open question 1.

with shipment as (

    select
        shipment_id,
        reference_number,
        customer_name,
        origin_site_code

    from {{ ref('stg_pangea__shipment') }}

),

sales_order as (

    select
        sales_order_number,
        ordering_customer_code,
        order_date,
        shipping_site_code,
        currency_code,
        primary_rep_code

    from {{ ref('stg_sage_x3__sorder') }}

),

customer_by_name as (

    -- customer_count is carried, not discarded. Zero BPCUSTOMER names collide
    -- today, so min() loses nothing - but this is the one model in the project
    -- that silently picks a winner, ten lines from int_customer_xref, which
    -- publishes is_ambiguous precisely so it does not have to. Publishing the
    -- count means a collision degrades into a visible warning rather than a
    -- wrong attribution. See the test on customer_name_is_ambiguous.
    select
        {{ name_upper('customer_name') }} as customer_name_upper,
        min(customer_code) as customer_code,
        count(*) as customer_count

    from {{ ref('stg_sage_x3__bpcustomer') }}
    group by 1

),

requested_delivery as (

    -- The customer's promise is a line-level date. A shipment is on time
    -- against the order only if it beats the latest line on that order -
    -- taking the earliest would flatter the metric.
    select
        sales_order_number,
        max(requested_delivery_date) as requested_delivery_date,
        min(requested_delivery_date) as earliest_requested_delivery_date

    from {{ ref('stg_sage_x3__sorderq') }}
    where requested_delivery_date is not null
    group by 1

),

final as (

    select
        shipment.shipment_id,
        sales_order.sales_order_number,
        requested_delivery.requested_delivery_date as customer_requested_delivery_date,
        sales_order.order_date,
        sales_order.currency_code                  as order_currency_code,
        sales_order.primary_rep_code,

        coalesce(sales_order.ordering_customer_code, customer_by_name.customer_code)
            as customer_code,

        case
            when sales_order.sales_order_number is not null then 'order_reference'
            when customer_by_name.customer_code is not null then 'customer_name'
            else 'unresolved'
        end as customer_resolution_method,

        sales_order.sales_order_number is not null as has_order_reference,
        coalesce(customer_by_name.customer_count, 0)  as customer_name_match_count,
        coalesce(customer_by_name.customer_count, 0) > 1
            and sales_order.sales_order_number is null as customer_name_is_ambiguous,
        shipment.reference_number is null          as reference_is_null,
        shipment.reference_number is not null
            and sales_order.sales_order_number is null as reference_is_unmatched

    from shipment
    left join sales_order
        on sales_order.sales_order_number = shipment.reference_number
    left join customer_by_name
        on customer_by_name.customer_name_upper = {{ name_upper('shipment.customer_name') }}
    left join requested_delivery
        on requested_delivery.sales_order_number = sales_order.sales_order_number

)

select * from final
