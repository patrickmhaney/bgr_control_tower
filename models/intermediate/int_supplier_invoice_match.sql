-- Grain: one row per supplier invoice line (NUM_0 + PIDLIN_0).
--
-- The three-way match. Each invoice line is compared to the purchase order
-- line it references and to the goods receipts posted against that PO line,
-- and the outcome is recorded as a reason rather than a bare boolean - "not
-- matched" is not actionable, "invoiced 20% more than was received" is.
--
-- An invoice line is compared to the receipt IT NAMES, not to every receipt
-- against the PO line. A PO line received in two deliveries is normally
-- invoiced twice, and comparing each invoice to the cumulative received
-- quantity would report a variance on both halves of a perfectly good
-- transaction. Where the invoice names no receipt, the PO line total is the
-- fallback and the line is reported as not_received.
--
-- Tolerances are vars, not literals. AP has not set a policy (open question
-- 14), so the metric is provisional and the sensitivity is one config change
-- away from being measurable.

{% set qty_tol = var('match_qty_tolerance_pct') %}
{% set price_tol = var('match_price_tolerance_pct') %}

with invoice_line as (

    select
        supplier_invoice_number,
        supplier_invoice_line_number,
        purchase_order_number,
        purchase_order_line_number,
        receipt_number,
        item_code,
        site_code,
        invoiced_qty,
        invoiced_unit_price,
        line_net_amount

    from {{ ref('stg_sage_x3__pinvoiced') }}

),

invoice_header as (

    select
        supplier_invoice_number,
        supplier_code,
        invoice_date,
        accounting_date,
        currency_code,
        invoice_status_code

    from {{ ref('stg_sage_x3__pinvoice') }}

),

purchase_order_line as (

    select
        purchase_order_number,
        purchase_order_line_number,
        ordered_qty,
        net_unit_price as ordered_unit_price

    from {{ ref('stg_sage_x3__porderq') }}

),

-- What the invoice line names: one receipt, one PO line.
receipt_at_line as (

    select
        receipt_number,
        purchase_order_number,
        purchase_order_line_number,
        sum(received_qty)   as received_qty,
        max(receipt_date)   as receipt_date

    from {{ ref('stg_sage_x3__preceiptd') }}
    group by 1, 2, 3

),

-- Everything ever received against the PO line, for context and for the
-- multi-delivery flag.
receipt_at_po_line as (

    select
        purchase_order_number,
        purchase_order_line_number,
        sum(received_qty)   as total_received_qty,
        max(receipt_date)   as last_receipt_date,
        count(distinct receipt_number) as receipt_count

    from {{ ref('stg_sage_x3__preceiptd') }}
    group by 1, 2

),

joined as (

    select
        invoice_line.*,
        invoice_header.supplier_code,
        invoice_header.invoice_date,
        invoice_header.accounting_date,
        invoice_header.currency_code,
        invoice_header.invoice_status_code,
        purchase_order_line.ordered_qty,
        purchase_order_line.ordered_unit_price,
        receipt_at_line.received_qty,
        receipt_at_line.receipt_date,
        receipt_at_po_line.total_received_qty,
        receipt_at_po_line.last_receipt_date,
        receipt_at_po_line.receipt_count

    from invoice_line
    inner join invoice_header using (supplier_invoice_number)
    left join purchase_order_line
        using (purchase_order_number, purchase_order_line_number)
    left join receipt_at_line
        using (receipt_number, purchase_order_number, purchase_order_line_number)
    left join receipt_at_po_line
        using (purchase_order_number, purchase_order_line_number)

),

variances as (

    select
        joined.*,

        joined.invoiced_qty - joined.received_qty            as qty_variance,
        joined.invoiced_unit_price - joined.ordered_unit_price
                                                            as price_variance,

        case when coalesce(joined.received_qty, 0) = 0 then null
             else abs(joined.invoiced_qty - joined.received_qty)
                  / abs(joined.received_qty) * 100
        end                                                 as qty_variance_pct,

        case when coalesce(joined.ordered_unit_price, 0) = 0 then null
             else abs(joined.invoiced_unit_price - joined.ordered_unit_price)
                  / abs(joined.ordered_unit_price) * 100
        end                                                 as price_variance_pct

    from joined

),

classified as (

    select
        variances.*,

        -- The reasons are ordered by severity: a line with no PO is not also
        -- reported as a price variance, because there is no price to compare.
        case
            when purchase_order_number is null       then 'no_purchase_order'
            when ordered_qty is null                 then 'po_line_not_found'
            when received_qty is null                then 'not_received'
            when qty_variance_pct  > {{ qty_tol }}   then 'quantity_variance'
            when price_variance_pct > {{ price_tol }} then 'price_variance'
            else 'matched'
        end                                                 as match_result

    from variances

)

select
    *,
    match_result = 'matched'                                as is_three_way_matched

from classified
