-- Grain: one row per calendar day.
--
-- MetricFlow requires a dedicated time spine. It is a projection of dim_date
-- rather than a second calendar, so there is exactly one definition of "a day"
-- in the project and no way for the two to drift.

select date_day
from {{ ref('dim_date') }}
