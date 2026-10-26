-- Grain: one row per golden employee (MDM contract C3), with their department.
-- Facts carry the employee who performed the activity, which is how a
-- department's impact is measured (decision D7).

with employee as (

    select * from {{ ref('conf_employee') }}

)

select
    cast(e.employee_key as varchar) as employee_key,
    cast(e.employee_name as varchar) as employee_name,
    cast(e.email as varchar) as email,
    cast(e.x3_user_code as varchar) as x3_user_code,
    cast(e.x3_rep_code as varchar) as x3_rep_code,
    cast(e.hubspot_owner_id as varchar) as hubspot_owner_id,
    cast(e.function_profile as varchar) as function_profile,
    cast(e.crm_team_name as varchar) as crm_team_name,
    cast(e.department_code as varchar) as department_code,
    cast(d.department_name as varchar) as department_name
from employee as e
left join {{ ref('dim_department') }} as d
    on d.department_code = e.department_code

union all

select 'E-UNKNOWN', 'System or unresolved user', null, null, null, null, null, null,
       'UNASSIGNED', 'Unassigned'
