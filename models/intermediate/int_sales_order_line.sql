-- Grain: one row per sales order line (SOHNUM_0 + SOPLIN_0).
--
-- X3 splits the order line across two tables: quantities in SORDERQ, prices in
-- SORDERP. Both carry ITMREF_0 and both agree on all 11,575 lines here, but
-- the README is explicit that the agreement should be checked in production
-- rather than assumed - so the model asserts it (see the test on
-- item_code_disagrees) instead of quietly preferring one side.

with quantity_side as (

    select
        sales_order_number,
        sales_order_line_number,
        item_code,
        shipping_site_code,
        ordered_qty,
        shipped_qty,
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
        line_net_amount,
        tax_code

    from {{ ref('stg_sage_x3__sorderp') }}

),

joined as (

    select
        quantity_side.*,
        price_side.item_code_price_side,
        price_side.item_description_at_order,
        price_side.gross_unit_price,
        price_side.net_unit_price,
        price_side.discount_amount,
        price_side.line_net_amount,
        price_side.tax_code

    from quantity_side
    inner join price_side
        on quantity_side.sales_order_number = price_side.sales_order_number
        and quantity_side.sales_order_line_number = price_side.sales_order_line_number

),

final as (

    select
        joined.*,
        joined.item_code is distinct from joined.item_code_price_side as item_code_disagrees

    from joined

)

select * from final
