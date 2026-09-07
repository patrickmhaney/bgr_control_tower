-- Grain: one row per calendar day, 2024-01-01 to 2027-12-31.
--
-- The one dimension every metric touches, which makes it the one place where a
-- wrong assumption is guaranteed to be expensive. Nothing in any source system
-- describes a fiscal calendar - there is no period table and no year-close
-- marker - so fiscal periods here are calendar periods offset by
-- var('fiscal_year_start_month'), currently 1.
--
-- If Finance runs a 4-4-5 or 13-period calendar, the offset is not enough and
-- this model needs a period definition table as a seed. See open question 4.
--
-- Unlike the other conformed dimensions this one carries no UNKNOWN member.
-- An integer date key has no natural sentinel that is not also a plausible
-- date, and a fact with no date is a fact with no place on a time series
-- rather than one attributable to an unknown day. Facts coalesce their other
-- foreign keys to 'UNKNOWN'; a null date key stays null and is excluded, which
-- is the honest treatment.

{% set fiscal_start_month = var('fiscal_year_start_month') %}

with spine as (

    select cast(range as date) as date_day
    from range(date '2024-01-01', date '2028-01-01', interval 1 day)

),

calendar as (

    select
        date_day,
        cast(strftime(date_day, '%Y%m%d') as integer)             as date_key,
        year(date_day)                                            as calendar_year,
        quarter(date_day)                                         as calendar_quarter,
        month(date_day)                                           as calendar_month,
        monthname(date_day)                                       as calendar_month_name,
        day(date_day)                                             as day_of_month,
        dayofweek(date_day)                                       as day_of_week,
        dayname(date_day)                                         as day_name,
        week(date_day)                                            as iso_week,
        date_trunc('week', date_day)                              as week_start_date,
        date_trunc('month', date_day)                             as month_start_date,
        last_day(date_day)                                        as month_end_date,
        date_trunc('quarter', date_day)                           as quarter_start_date,
        date_trunc('year', date_day)                              as year_start_date,
        dayofweek(date_day) in (0, 6)                             as is_weekend

    from spine

),

fiscal as (

    select
        calendar.*,
        -- Shift the calendar back by (start_month - 1) months and read the
        -- calendar year and quarter off the shifted date. With a start month
        -- of 1 this is the identity, which is the documented assumption.
        year(date_day - to_months({{ fiscal_start_month - 1 }}))    as fiscal_year,
        quarter(date_day - to_months({{ fiscal_start_month - 1 }})) as fiscal_quarter,
        month(date_day - to_months({{ fiscal_start_month - 1 }}))   as fiscal_month_number,
        {{ fiscal_start_month }}                                    as fiscal_year_start_month

    from calendar

),

final as (

    select
        fiscal.*,
        'FY' || cast(fiscal_year as varchar)                                     as fiscal_year_label,
        'FY' || cast(fiscal_year as varchar) || '-Q' || cast(fiscal_quarter as varchar)
                                                                                 as fiscal_quarter_label,
        cast(calendar_year as varchar) || '-' || lpad(cast(calendar_month as varchar), 2, '0')
                                                                                 as calendar_month_label,
        -- Named for what it is. `is_past` in a table materialisation is
        -- correct on build day and progressively wrong afterwards - it was the
        -- only non-deterministic column in the core, and it made dim_date the
        -- one table that changed without an input changing. The build date
        -- sits beside it so a stale value is visible rather than silent, and
        -- Power BI should compute "is past" against TODAY() rather than read
        -- this column.
        date_day <= current_date                                as is_past_as_of_build,
        cast(current_date as date)                              as built_on_date,
        {{ fiscal_start_month }} = 1                                             as fiscal_equals_calendar

    from fiscal

)

select * from final
