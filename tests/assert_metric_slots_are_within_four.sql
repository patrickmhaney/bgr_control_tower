-- Each dashboard carries four metrics. More than four in the map means either
-- the dashboard spec changed or someone mapped a metric to the wrong process.

select
    process_code,
    count(*) as metric_count

from {{ ref('process_metric_map') }}
group by 1
having count(*) > 4
