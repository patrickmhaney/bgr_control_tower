{{ config(materialized='table') }}

-- Grain: one row per (source system record, Paycom person) match candidate.
--
-- Paycom is the roster of record, so it is the spine. Two problems have to be
-- solved in order, and solving them in the wrong order produces a plausible
-- model that is quietly wrong:
--
--   1. Paycom contains duplicate people. 12 of 150 rows are the same person
--      twice - same legal name, same work_email, two employee_codes. Matching
--      across systems before collapsing these gives every duplicated person
--      two matches and inflates every downstream count.
--   2. Only then can the cross-system probes run. X3 REPRESENT shares only a
--      name ("LASTNAME FIRSTNAME"); HubSpot owner shares an email, which is a
--      far better key and is not in the README's join map.

with paycom_employee as (

    select
        employee_code,
        legal_first_name,
        legal_last_name,
        work_email,
        employment_status,
        department_code,
        department_name,
        payroll_location_code,
        position_title,
        hire_date,
        {{ person_key('legal_last_name', 'legal_first_name') }} as person_name_key

    from {{ ref('stg_paycom__employee') }}

),

paycom_person as (

    -- Collapse duplicates on email, which is the strongest within-Paycom
    -- identity signal available. The surviving row is the earliest hire, on
    -- the assumption that the later record is the accidental re-creation.
    -- duplicate_record_count keeps the problem visible rather than resolving
    -- it out of sight.
    select
        arg_min(employee_code, coalesce(hire_date, date '2100-01-01')) as employee_code,
        lower(work_email)                                              as work_email,
        min(person_name_key)                                           as person_name_key,
        count(*)                                                       as duplicate_record_count,
        string_agg(employee_code, ',' order by employee_code)          as all_employee_codes

    from paycom_employee
    where work_email is not null
    group by lower(work_email)

),

x3_rep as (

    select
        rep_code,
        rep_name,
        site_code,
        upper(trim(rep_name)) as person_name_key

    from {{ ref('stg_sage_x3__represent') }}

),

hubspot_owner as (

    select
        owner_id,
        email,
        first_name,
        last_name,
        is_archived

    from {{ ref('stg_hubspot__owner') }}

),

candidate as (

    select
        'hubspot' as source_system,
        hubspot_owner.owner_id as source_key,
        hubspot_owner.first_name || ' ' || hubspot_owner.last_name as source_label,
        paycom_person.employee_code,
        'work_email' as match_method,
        0.99 as confidence
    from hubspot_owner
    inner join paycom_person
        on lower(trim(hubspot_owner.email)) = paycom_person.work_email

    union all

    select
        'sage_x3',
        x3_rep.rep_code,
        x3_rep.rep_name,
        paycom_person.employee_code,
        'person_name',
        0.70
    from x3_rep
    inner join paycom_person
        on x3_rep.person_name_key = paycom_person.person_name_key

),

ranked as (

    select
        candidate.*,
        row_number() over (
            partition by source_system, source_key
            order by confidence desc, employee_code
        ) as candidate_rank,
        count(*) over (
            partition by source_system, source_key
        ) as candidate_count

    from candidate

),

final as (

    select
        {{ dbt_utils.generate_surrogate_key([
            'ranked.source_system', 'ranked.source_key', 'ranked.employee_code'
        ]) }} as employee_xref_key,
        ranked.source_system,
        ranked.source_key,
        ranked.source_label,
        ranked.employee_code                       as paycom_employee_code,
        paycom_person.work_email,
        paycom_person.duplicate_record_count,
        paycom_person.all_employee_codes,
        ranked.match_method,
        cast(ranked.confidence as decimal(4, 2))   as confidence,
        ranked.candidate_rank,
        ranked.candidate_count > 1                 as is_ambiguous,
        ranked.candidate_rank = 1                  as is_selected

    from ranked
    inner join paycom_person on paycom_person.employee_code = ranked.employee_code

)

select * from final
