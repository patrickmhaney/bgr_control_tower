{% set start = var('fiscal_year_start_month') | int %}
{# Months to add so a fiscal year lines up with a calendar year. A fiscal year
   is named by the calendar year it ends in. 0 when fiscal = calendar. #}
{% set shift = 0 if start == 1 else 13 - start %}

-- Grain: one row per day. The conformed calendar, and MetricFlow's time spine.
-- Fiscal periods follow var('fiscal_year_start_month') - open question 4.

with spine as (

    {{ dbt_utils.date_spine(datepart="day",
                            start_date="cast('2024-01-01' as date)",
                            end_date="cast('2028-01-01' as date)") }}

),

days as (

    select
        cast(date_day as date) as date_day,
        cast({{ dbt.dateadd('month', shift, 'date_day') }} as date) as fiscal_shifted
    from spine

)

select
    date_day,
    cast({{ date_part('year', 'date_day') }} as integer) as calendar_year,
    cast({{ date_part('quarter', 'date_day') }} as integer) as calendar_quarter,
    cast({{ date_part('month', 'date_day') }} as integer) as calendar_month,
    {{ dbt.concat(["cast(" ~ date_part('year', 'date_day') ~ " as " ~ dbt.type_string() ~ ")",
                   "'-'",
                   "right(" ~ dbt.concat(["'0'", "cast(" ~ date_part('month', 'date_day') ~ " as " ~ dbt.type_string() ~ ")"]) ~ ", 2)"]) }}
        as calendar_month_label,
    {{ dbt.concat(["cast(" ~ date_part('year', 'date_day') ~ " as " ~ dbt.type_string() ~ ")",
                   "'-Q'",
                   "cast(" ~ date_part('quarter', 'date_day') ~ " as " ~ dbt.type_string() ~ ")"]) }}
        as calendar_quarter_label,
    cast({{ dbt.date_trunc('month', 'date_day') }} as date) as month_start_date,
    cast({{ date_part('year', 'fiscal_shifted') }} as integer) as fiscal_year,
    cast({{ date_part('quarter', 'fiscal_shifted') }} as integer) as fiscal_quarter,
    {{ dbt.concat(["'FY'", "cast(" ~ date_part('year', 'fiscal_shifted') ~ " as " ~ dbt.type_string() ~ ")"]) }}
        as fiscal_year_label,
    {{ dbt.concat(["'FY'", "cast(" ~ date_part('year', 'fiscal_shifted') ~ " as " ~ dbt.type_string() ~ ")",
                   "'-Q'", "cast(" ~ date_part('quarter', 'fiscal_shifted') ~ " as " ~ dbt.type_string() ~ ")"]) }}
        as fiscal_quarter_label,
    cast({{ dbt.dateadd('month', -shift, dbt.date_trunc('quarter', 'fiscal_shifted')) }} as date)
        as fiscal_quarter_start_date,
    cast({{ dbt.dateadd('month', -shift, dbt.date_trunc('year', 'fiscal_shifted')) }} as date)
        as fiscal_year_start_date
from days
