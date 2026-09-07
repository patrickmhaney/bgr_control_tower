-- Every process in the map must exist in the process seed.
--
-- The reverse is deliberately NOT asserted. Six of the nine processes have no
-- metrics, and that is a valid state the architecture has to tolerate - an
-- unmapped process is a business gap, not a build failure.

select
    map.process_code

from {{ ref('process_metric_map') }} as map
left join {{ ref('process') }} as process
    on process.process_code = map.process_code
where process.process_code is null
