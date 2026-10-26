{% set qty_tol = var('match_qty_tolerance_pct') %}
{% set price_tol = var('match_price_tolerance_pct') %}

-- Grain: one row per supplier invoice line (NUM_0 + PIDLIN_0).
--
-- The three-way match: does the invoice agree with what was ordered and what
-- arrived? Quantity is compared with the receipt it was billed from, price
-- with the purchase order line. Tolerances are vars (open question 14).
-- A line that cannot be matched is classified, never dropped: the reason is
-- the useful part.

with invoice_line as (

    select * from {{ ref('stg_sage_x3__pinvoiced') }}

),

invoice_header as (

    select * from {{ ref('stg_sage_x3__pinvoice') }}

),

po_line as (

    select purchase_order_number, purchase_order_line_number, ordered_qty,
           net_unit_price as ordered_unit_price
    from {{ ref('stg_sage_x3__porderq') }}

),

po_header as (

    select purchase_order_number, created_by as po_created_by
    from {{ ref('stg_sage_x3__porder') }}

),

receipt_at_line as (

    select receipt_number, purchase_order_number, purchase_order_line_number,
           sum(received_qty) as received_qty, max(receipt_date) as receipt_date
    from {{ ref('stg_sage_x3__preceiptd') }}
    group by receipt_number, purchase_order_number, purchase_order_line_number

),

receipt_count as (

    select purchase_order_number, purchase_order_line_number,
           count(distinct receipt_number) as receipt_count
    from {{ ref('stg_sage_x3__preceiptd') }}
    group by purchase_order_number, purchase_order_line_number

),

joined as (

    select
        il.supplier_invoice_number,
        il.supplier_invoice_line_number,
        il.purchase_order_number,
        il.purchase_order_line_number,
        il.receipt_number,
        il.item_code,
        il.site_code,
        il.invoiced_qty,
        il.invoiced_unit_price,
        il.line_net_amount,
        ih.supplier_code,
        ih.invoice_date,
        ih.accounting_date,
        ih.currency_code,
        ih.invoice_status_code,
        ph.po_created_by,
        pl.ordered_qty,
        pl.ordered_unit_price,
        r.received_qty,
        r.receipt_date,
        coalesce(rc.receipt_count, 0) as receipt_count
    from invoice_line as il
    inner join invoice_header as ih
        on ih.supplier_invoice_number = il.supplier_invoice_number
    left join po_header as ph
        on ph.purchase_order_number = il.purchase_order_number
    left join po_line as pl
        on pl.purchase_order_number = il.purchase_order_number
        and pl.purchase_order_line_number = il.purchase_order_line_number
    left join receipt_at_line as r
        on r.receipt_number = il.receipt_number
        and r.purchase_order_number = il.purchase_order_number
        and r.purchase_order_line_number = il.purchase_order_line_number
    left join receipt_count as rc
        on rc.purchase_order_number = il.purchase_order_number
        and rc.purchase_order_line_number = il.purchase_order_line_number

),

variances as (

    select
        joined.*,
        case when coalesce(received_qty, 0) = 0 then null
             else abs(invoiced_qty - received_qty) / abs(received_qty) * 100 end as qty_variance_pct,
        case when coalesce(ordered_unit_price, 0) = 0 then null
             else abs(invoiced_unit_price - ordered_unit_price) / abs(ordered_unit_price) * 100
        end as price_variance_pct
    from joined

)

select
    variances.*,
    case
        when purchase_order_number is null then 'no_purchase_order'
        when ordered_qty is null then 'po_line_not_found'
        when received_qty is null then 'not_received'
        when qty_variance_pct > {{ qty_tol }} then 'quantity_variance'
        when price_variance_pct > {{ price_tol }} then 'price_variance'
        else 'matched'
    end as match_result
from variances
