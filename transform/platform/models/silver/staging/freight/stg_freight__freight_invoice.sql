-- Cleaning only: no business logic.
-- Grain: One row per carrier invoice, for one shipment.
with source as (
    select * from {{ ref('bronze_freight__freight_invoice') }}
),

cleaned as (

    select
        {{ clean_str('invoice_id') }} as invoice_id,
        {{ clean_str('shipment_id') }} as shipment_id,
        upper({{ clean_str('carrier_code') }}) as carrier_code,
        cast(invoice_date as date) as invoice_date,
        upper({{ clean_str('currency') }}) as currency_code,
        cast(line_haul as decimal(18, 2)) as line_haul_amount,
        cast(fuel_surcharge as decimal(18, 2)) as fuel_surcharge_amount,
        cast(accessorial as decimal(18, 2)) as accessorial_amount

    from source

)

select * from cleaned
