-- Grain: one row per department. Placeholders from the seed (open question Q-A).

select
    cast(department_code as varchar) as department_code,
    cast(department_name as varchar) as department_name,
    cast(display_order as integer) as display_order
from {{ ref('department') }}
