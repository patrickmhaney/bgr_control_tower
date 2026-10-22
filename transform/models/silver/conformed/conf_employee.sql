-- Grain: one row per golden employee, with the department their work counts toward.
--
-- Decision D7: a department's activity is the activity of its people. The
-- department comes from the X3 user's function profile, or failing that the
-- HubSpot owner's team, through two seeds - the departments themselves are
-- placeholders until the business defines them (open question Q-A).

with golden as (

    select * from {{ source('mdm', 'mdm_golden_employee') }}

),

x3_user as (

    select user_code, function_profile, site_code
    from {{ ref('stg_sage_x3__autilis') }}

),

owner as (

    select owner_id, team_name
    from {{ ref('stg_hubspot__owner') }}

)

select
    g.golden_key as employee_key,
    g.display_name as employee_name,
    g.email,
    g.x3_user_code,
    g.x3_rep_code,
    g.hubspot_owner_id,
    u.function_profile,
    o.team_name as crm_team_name,
    u.site_code,
    coalesce(by_profile.department_code, by_team.department_code, 'UNASSIGNED') as department_code
from golden as g
left join x3_user as u
    on u.user_code = g.x3_user_code
left join owner as o
    on o.owner_id = g.hubspot_owner_id
left join {{ ref('function_profile_department') }} as by_profile
    on by_profile.function_profile = u.function_profile
left join {{ ref('hubspot_team_department') }} as by_team
    on by_team.team_name = o.team_name
