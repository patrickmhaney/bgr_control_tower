{#-
    Turn a bronze changelog into the source table's current state.

    Bronze is append-only (contract C2). Every row carries `_op` (S snapshot,
    I insert, U update/upsert, D delete) and `_change_seq`, which orders the
    rows of one table. One rule covers every extraction strategy:

      1. Start from the most recent snapshot, if there is one. A snapshot
         (`_op = 'S'`) is complete, so anything older than it is superseded.
         For full-refresh tables every load is a snapshot, so this keeps the
         latest load. For X3 it keeps the initial snapshot plus every CDC row
         after it, or the latest resnapshot after a retention gap.
      2. Keep the latest row per key by `_change_seq`.
      3. Drop keys whose latest row is a delete.

    This is the only layer allowed engine-specific SQL (rule 3 in PLAN.md
    §9.3): another ingestion tool gets its own adapter macro with the same
    output shape - source columns unchanged, plus `_change_seq` and
    `_loaded_at` - and nothing in silver changes.
-#}
{% macro bronze_current(source_name, table_name, keys) %}
with changelog as (

    select * from {{ source(source_name, table_name) }}

),

latest_snapshot as (

    select max(_change_seq) as snapshot_seq from changelog where _op = 'S'

),

in_scope as (

    select changelog.*
    from changelog
    cross join latest_snapshot
    where latest_snapshot.snapshot_seq is null
       or changelog._change_seq >= latest_snapshot.snapshot_seq

),

latest as (

    select *
    from in_scope
    qualify row_number() over (
        partition by {{ keys | join(', ') }}
        order by _change_seq desc, _dlt_load_id desc
    ) = 1

)

select
    * exclude (_op, _extracted_at, _dlt_load_id, _dlt_id),
    _extracted_at as _loaded_at
from latest
where _op <> 'D'
{% endmacro %}
