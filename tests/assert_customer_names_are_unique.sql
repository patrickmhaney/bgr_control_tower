-- int_shipment_order falls back to matching pangea.shipment.customer_name
-- against BPCUSTOMER.BPCNAM_0 for the 511 shipments carrying no resolvable
-- order reference. That fallback is only sound while ERP customer names are
-- unique: two customers sharing a name would silently attribute shipments to
-- whichever one sorts first.
--
-- Zero names collide in this extract, but the two-company mock cannot
-- establish that it holds in a production folder. See open question 13.

select
    upper(trim(customer_name)) as customer_name_upper,
    count(*) as customers,
    string_agg(customer_code, ', ' order by customer_code) as codes

from {{ ref('stg_sage_x3__bpcustomer') }}
group by 1
having count(*) > 1
