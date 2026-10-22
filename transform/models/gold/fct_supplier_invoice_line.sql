-- Grain: one row per supplier invoice line, with its three-way match outcome.
-- Feeds Match Rate. The buyer who raised the purchase order is the employee,
-- so purchasing's share of mismatches is visible (decision D7).

with matched as (

    select * from {{ ref('int_supplier_invoice_match') }}

)

select
    cast(supplier_invoice_number as varchar) as supplier_invoice_number,
    cast(supplier_invoice_line_number as bigint) as supplier_invoice_line_number,
    cast(invoice_date as date) as invoice_date,
    cast(coalesce(item_code, 'UNKNOWN') as varchar) as item_code,
    cast(coalesce(site_code, 'UNKNOWN') as varchar) as site_code,
    cast(coalesce(supplier_code, 'UNKNOWN') as varchar) as supplier_code,
    cast({{ employee_key('po_created_by') }} as varchar) as employee_key,
    cast(purchase_order_number as varchar) as purchase_order_number,
    cast(receipt_number as varchar) as receipt_number,
    cast(match_result as varchar) as match_result,
    cast(invoiced_qty as decimal(18, 4)) as invoiced_qty,
    cast(received_qty as decimal(18, 4)) as received_qty,
    cast(line_net_amount as decimal(18, 4)) as line_net_amount_usd,
    cast(qty_variance_pct as decimal(18, 4)) as qty_variance_pct,
    cast(price_variance_pct as decimal(18, 4)) as price_variance_pct,
    cast({{ flag("match_result = 'matched'") }} as integer) as is_three_way_matched,
    cast({{ flag('purchase_order_number is null') }} as integer) as is_maverick_spend,
    cast({{ flag('receipt_count > 1') }} as integer) as is_multi_delivery,
    cast(1 as integer) as invoice_line_count
from matched
