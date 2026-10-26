-- Grain: one row per site. X3 codes are the conformed key.

with facility as (

    select * from {{ ref('stg_sage_x3__facility') }}

),

company as (

    select company_code, company_name from {{ ref('stg_sage_x3__company') }}

)

select
    cast(f.site_code as varchar) as site_code,
    cast(f.site_name as varchar) as site_name,
    cast(f.city as varchar) as city,
    cast(f.state_province as varchar) as state_province,
    cast(f.country_code as varchar) as country_code,
    cast(f.company_code as varchar) as company_code,
    cast(c.company_name as varchar) as company_name,
    cast(x.netstock_location_code as varchar) as netstock_location_code
from facility as f
left join company as c
    on c.company_code = f.company_code
left join {{ ref('site_code_crosswalk') }} as x
    on x.x3_site_code = f.site_code

union all

select 'UNKNOWN', 'Unresolved', null, null, null, null, null, null
