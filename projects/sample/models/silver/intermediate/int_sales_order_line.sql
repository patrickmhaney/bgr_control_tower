-- Grain: one row per sales order line (SOHNUM_0 + SOPLIN_0).
--
-- X3 splits an order line across two tables: quantities in SORDERQ, prices in
-- SORDERP. Both carry ITMREF_0. They agree here, but that should be checked in
-- production rather than assumed, so the model publishes item_code_disagrees
-- and a test asserts it is always 0 instead of quietly preferring one side.

with quantity_side as (

    select
        sales_order_number,
        sales_order_line_number,
        item_code,
        shipping_site_code,
        ordered_qty,
        shortage_qty,
        requested_delivery_date,
        unit_of_measure
    from {{ ref('stg_sage_x3__sorderq') }}

),

price_side as (

    select
        sales_order_number,
        sales_order_line_number,
        item_code as item_code_price_side,
        item_description_at_order,
        gross_unit_price,
        net_unit_price,
        discount_amount,
        line_net_amount
    from {{ ref('stg_sage_x3__sorderp') }}

)

select
    q.sales_order_number,
    q.sales_order_line_number,
    q.item_code,
    q.shipping_site_code,
    q.ordered_qty,
    q.shortage_qty,
    q.requested_delivery_date,
    q.unit_of_measure,
    p.item_description_at_order,
    p.gross_unit_price,
    p.net_unit_price,
    p.discount_amount,
    p.line_net_amount,
    {{ platform.flag("coalesce(q.item_code, '') <> coalesce(p.item_code_price_side, '')") }} as item_code_disagrees
from quantity_side as q
inner join price_side as p
    on q.sales_order_number = p.sales_order_number
    and q.sales_order_line_number = p.sales_order_line_number
