-- Cleaning only: no business logic.
-- Grain: One row per sales order header.
with source as (
    select * from {{ ref('bronze_sage_x3__sorder') }}
),

cleaned as (

    select
        {{ clean_str('SOHNUM_0') }} as sales_order_number,
        {{ clean_str('SALFCY_0') }} as sales_site_code,
        {{ clean_str('STOFCY_0') }} as shipping_site_code,
        {{ clean_str('BPCORD_0') }} as ordering_customer_code,
        {{ clean_str('BPCINV_0') }} as invoicing_customer_code,
        {{ x3_date('ORDDAT_0') }} as order_date,
        {{ x3_date('SHIDAT_0') }} as shipment_date,
        {{ clean_str('CUR_0') }} as currency_code,
        cast(ORDSTA_0 as bigint) as order_status_code,
        {{ clean_str('REP_0') }} as primary_rep_code,
        {{ clean_str('REP_1') }} as secondary_rep_code,
        cast(TOTLINAMT_0 as decimal(18, 4)) as order_total_amount,
        cast(ORDINVSTA_0 as bigint) as invoicing_status_code,
        {{ clean_str('CREUSR_0') }} as created_by,
        {{ x3_date('CREDAT_0') }} as created_date,
        {{ x3_date('UPDDAT_0') }} as updated_date,
        cast(UPDTICK_0 as bigint) as update_tick

    from source

),

decoded_order_status as (

    select
        base.*,
        menu.menu_label as order_status

    from cleaned as base
    left join {{ ref('stg_sage_x3__aplstd') }} as menu
        on menu.menu_chapter = 415
        and menu.menu_code = base.order_status_code
        and menu.language_code = 'ENG'

)

select * from decoded_order_status
