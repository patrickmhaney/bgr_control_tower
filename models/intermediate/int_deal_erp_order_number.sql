-- Grain: one row per HubSpot deal that carries an ERP order reference, after
-- repair. A deal naming two orders emits two rows.
--
-- The CRM-to-ERP handoff is the dirtiest link in the estate: 145 of 238
-- closed-won deals carry a reference and only 96 join as-is. Three failure
-- modes, all mechanical and all repairable:
--
--   lowercased        sous26001710  ->  SOUS26001710
--   prefix stripped   US25000718    ->  SOUS25000718
--   two in one field  "SOUS25002068 / SOUS24001818"
--
-- Repair happens here rather than in staging because it is business logic - it
-- encodes an assumption about what a user meant to type. Staging stays
-- lossless; this model is where the guessing is declared and measured.

with deal as (

    select
        deal_id,
        erp_order_number_raw,
        is_closed_won,
        is_archived,
        deal_amount,
        close_date

    from {{ ref('stg_hubspot__deal') }}
    where erp_order_number_raw is not null

),

split_multi as (

    -- " / " separated pairs become one row each. unnest keeps the deal_id, so
    -- a two-order deal correctly claims both orders.
    select
        deal.*,
        trim(part) as reference_part

    from deal,
    unnest(string_split(deal.erp_order_number_raw, '/')) as t(part)

),

normalized as (

    select
        deal_id,
        erp_order_number_raw,
        is_closed_won,
        is_archived,
        deal_amount,
        close_date,
        reference_part,
        upper(trim(reference_part)) as reference_upper

    from split_multi
    where nullif(trim(reference_part), '') is not null

),

repaired as (

    select
        normalized.*,
        -- X3 sales order numbers are SO + country + year + sequence. A
        -- reference that starts with the country code alone lost the SO
        -- prefix on the way out of HubSpot.
        case
            when regexp_matches(reference_upper, '^SO(US|CA)[0-9]{8}$')
                then reference_upper
            when regexp_matches(reference_upper, '^(US|CA)[0-9]{8}$')
                then 'SO' || reference_upper
        end as repaired_order_number,
        -- Independent flags, not a priority chain. A case expression testing
        -- case_corrected first labels a reference that was both split out of a
        -- two-order field AND lowercased as 'case_corrected' only, so it never
        -- appears in the split count. No deal in this extract is both, so the
        -- published counts happen to be right - but they are presented as four
        -- distinct failure modes, and in production they would stop being that.
        strpos(erp_order_number_raw, '/') > 0                        as was_split,
        reference_upper <> trim(reference_part)                      as was_case_corrected,
        regexp_matches(reference_upper, '^(US|CA)[0-9]{8}$')         as was_prefix_restored

    from normalized

),

final as (

    select
        repaired.deal_id,
        repaired.erp_order_number_raw,
        repaired.repaired_order_number   as sales_order_number,
        repaired.was_split,
        repaired.was_case_corrected,
        repaired.was_prefix_restored,
        -- A readable label derived from the flags, joining every repair that
        -- fired rather than reporting only the first.
        case
            when not (repaired.was_split or repaired.was_case_corrected
                      or repaired.was_prefix_restored) then 'as_is'
            else concat_ws(
                ' + ',
                case when repaired.was_split then 'split_multi_value' end,
                case when repaired.was_case_corrected then 'case_corrected' end,
                case when repaired.was_prefix_restored then 'prefix_restored' end
            )
        end                              as repair_applied,
        repaired.is_closed_won,
        repaired.is_archived,
        repaired.deal_amount,
        repaired.close_date,
        sales_order.sales_order_number is not null as resolves_to_order,
        count(*) over (partition by repaired.deal_id) as references_on_deal

    from repaired
    left join {{ ref('stg_sage_x3__sorder') }} as sales_order
        on sales_order.sales_order_number = repaired.repaired_order_number

)

select * from final
