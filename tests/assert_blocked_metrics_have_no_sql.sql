-- A blocked metric must not have a generated SQL model.
--
-- The failure this guards against is subtle and expensive: someone unblocks a
-- metric in the registry by adding SQL but forgets to change its status, or
-- adds a "temporary" proxy under a blocked metric's name. Either way a number
-- appears on a dashboard under a name the business believes is unavailable,
-- and nobody questions it because the tile is populated.

select
    metric_name,
    status,
    sql_model

from {{ ref('metric_registry') }}
where status = 'blocked'
  and nullif(sql_model, '') is not null
