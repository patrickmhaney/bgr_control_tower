-- Grain: one row per sales invoice or credit memo line.
-- Feeds DSO (days-to-pay proxy), Unsettled Invoice Rate and revenue. Lines
-- net of credit memos reconcile to GL account 41000 (a tested assertion).
-- Invoices carry no creator, so these metrics cannot be cut by department and
-- MetricFlow refuses the request rather than guessing.

with line as (

    select * from {{ ref('stg_sage_x3__sinvoiced') }}

),

header as (

    select * from {{ ref('stg_sage_x3__sinvoicev') }}

),

terms as (

    select customer_code, payment_term_code from {{ ref('stg_sage_x3__bpcustomer') }}

),

joined as (

    select
        line.*,
        header.invoice_type_code,
        header.invoice_date,
        header.payment_date,
        header.customer_code,
        header.currency_code,
        terms.payment_term_code
    from line
    inner join header
        on header.invoice_number = line.invoice_number
    left join terms
        on terms.customer_code = header.customer_code

)

select
    cast(invoice_number as varchar) as invoice_number,
    cast(invoice_line_number as bigint) as invoice_line_number,
    cast(invoice_date as date) as invoice_date,
    cast(payment_date as date) as payment_date,
    cast({{ platform.customer_key('sage_x3', 'customer_code') }} as varchar) as customer_key,
    cast(coalesce(item_code, 'UNKNOWN') as varchar) as item_code,
    cast(coalesce(shipping_site_code, 'UNKNOWN') as varchar) as site_code,
    cast(sales_order_number as varchar) as sales_order_number,
    cast(invoice_type_code as varchar) as invoice_type_code,
    cast(payment_term_code as varchar) as payment_term_code,
    cast(currency_code as varchar) as document_currency_code,
    cast(invoiced_qty as decimal(18, 4)) as invoiced_qty,
    cast(line_net_amount as decimal(18, 4)) as line_net_amount_doc,
    cast({{ platform.to_usd('line_net_amount', 'currency_code', 'invoice_date') }} as decimal(18, 4)) as line_net_amount_usd,
    cast({{ platform.flag('payment_date is not null') }} as integer) as is_settled,
    cast({{ platform.flag('payment_date is null') }} as integer) as is_unsettled,
    cast(case when payment_date is null then null
              else {{ dbt.datediff('invoice_date', 'payment_date', 'day') }} end as integer)
        as days_to_pay_settled_only,
    cast(1 as integer) as invoice_line_count
from joined
