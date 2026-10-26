-- Grain: one row per customer return line (SRHNUM_0 + SRDLIN_0).
--
-- Resolves a return to the order line it reverses. 8% of returns carry an
-- order number that is blank or lower-cased, keyed from a packing slip. Two
-- probes, in order: the reference as given, then upper(trim(reference)).
-- Returns that resolve to nothing are kept (is_orphan_return = 1): dropping
-- them would understate Return Rate's numerator and leave its denominator
-- alone - the failure that makes a metric quietly optimistic.

with return_line as (

    select * from {{ ref('stg_sage_x3__sreturnd') }}

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

    select sales_order_number, sales_order_line_number
    from {{ ref('int_sales_order_line') }}

)

select
    rl.return_number,
    rl.return_line_number,
    coalesce(exact_match.sales_order_number, normalised.sales_order_number) as sales_order_number,
    rl.sales_order_line_number,
    rl.sales_order_number as sales_order_number_raw,
    case
        when exact_match.sales_order_number is not null then 'exact'
        when normalised.sales_order_number is not null then 'normalised'
    end as order_match_method,
    rh.customer_code,
    coalesce(rl.site_code, rh.return_site_code) as site_code,
    rl.item_code,
    rh.return_date,
    rh.invoice_number,
    rh.return_status,
    rl.return_reason_code,
    rl.return_reason,
    rl.returned_qty,
    rl.net_unit_price,
    rl.line_net_amount,
    {{ platform.flag('exact_match.sales_order_number is null and normalised.sales_order_number is null') }}
        as is_orphan_return
from return_line as rl
inner join return_header as rh
    on rh.return_number = rl.return_number
left join order_line as exact_match
    on exact_match.sales_order_number = rl.sales_order_number
    and exact_match.sales_order_line_number = rl.sales_order_line_number
left join order_line as normalised
    on normalised.sales_order_number = upper(trim(rl.sales_order_number))
    and normalised.sales_order_line_number = rl.sales_order_line_number
