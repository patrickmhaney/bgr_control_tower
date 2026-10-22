-- Cleaning only: no business logic.
-- Grain: One row per sales order line (price side).
with source as (
    select * from {{ ref('bronze_sage_x3__sorderp') }}
),

cleaned as (

    select
        {{ clean_str('SOHNUM_0') }} as sales_order_number,
        cast(SOPLIN_0 as bigint) as sales_order_line_number,
        cast(SOPSEQ_0 as bigint) as sales_order_line_sequence,
        {{ clean_str('ITMREF_0') }} as item_code,
        {{ clean_str('ITMDES1_0') }} as item_description_at_order,
        cast(GROPRI_0 as decimal(18, 4)) as gross_unit_price,
        cast(NETPRI_0 as decimal(18, 4)) as net_unit_price,
        cast(DISCRGVAL1_0 as decimal(18, 4)) as discount_amount,
        cast(AMTNOTLIN_0 as decimal(18, 4)) as line_net_amount,
        {{ clean_str('VAT1_0') }} as tax_code,
        cast(UPDTICK_0 as bigint) as update_tick

    from source

)

select * from cleaned
