-- Grain: one row per customer return line (SRHNUM_0 + SRDLIN_0).
--
-- Resolves a return back to the order line it reverses. The reference is not
-- reliable: 8% of returns arrive with an order number that is blank or
-- lowercased, keyed from a packing slip rather than copied from the order.
-- Two probes, in order, mirroring int_customer_xref's approach:
--
--   exact       SOHNUM_0 matches an order line directly.
--   normalised  upper(trim(SOHNUM_0)) matches. Recovers the lowercased ones.
--
-- Returns that resolve to no order line are KEPT, with a null order reference
-- and is_orphan_return = true. They are real returns and dropping them would
-- understate the numerator of Return Rate while leaving its denominator
-- untouched - the failure mode that makes a metric quietly optimistic.

with return_line as (

    select
        return_number,
        return_line_number,
        item_code,
        returned_qty,
        net_unit_price,
        line_net_amount,
        sales_order_number as sales_order_number_raw,
        sales_order_line_number,
        site_code,
        return_reason_code,
        return_reason

    from {{ ref('stg_sage_x3__sreturnd') }}

),

return_header as (

    select
        return_number,
        site_code as return_site_code,
        customer_code,
        return_date,
        invoice_number,
        return_status

    from {{ ref('stg_sage_x3__sreturn') }}

),

order_line as (

    select
        sales_order_number,
        sales_order_line_number,
        item_code,
        line_net_amount as order_line_net_amount

    from {{ ref('int_sales_order_line') }}

),

probed as (

    select
        return_line.*,
        return_header.return_site_code,
        return_header.customer_code,
        return_header.return_date,
        return_header.invoice_number,
        return_header.return_status,

        -- Probe 1 then probe 2. coalesce is the ranking.
        coalesce(exact.sales_order_number, normalised.sales_order_number)
                                                        as sales_order_number,
        case
            when exact.sales_order_number is not null then 'exact'
            when normalised.sales_order_number is not null then 'normalised'
        end                                             as order_match_method

    from return_line
    inner join return_header using (return_number)

    left join order_line as exact
        on exact.sales_order_number = return_line.sales_order_number_raw
        and exact.sales_order_line_number = return_line.sales_order_line_number

    left join order_line as normalised
        on normalised.sales_order_number = upper(trim(return_line.sales_order_number_raw))
        and normalised.sales_order_line_number = return_line.sales_order_line_number

),

final as (

    select
        return_number,
        return_line_number,
        sales_order_number,
        sales_order_line_number,
        sales_order_number_raw,
        order_match_method,
        customer_code,
        coalesce(site_code, return_site_code)            as site_code,
        item_code,
        return_date,
        invoice_number,
        return_status,
        return_reason_code,
        return_reason,
        returned_qty,
        net_unit_price,
        line_net_amount,
        sales_order_number is null                       as is_orphan_return

    from probed

)

select * from final
