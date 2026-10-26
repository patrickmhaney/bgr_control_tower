-- Current state of freight.freight_invoice, from the bronze changelog.
{{ platform.bronze_current('freight', 'freight_invoice', ['invoice_id']) }}
