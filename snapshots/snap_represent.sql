{% snapshot snap_represent %}
    select * from {{ ref('stg_sage_x3__represent') }}
{% endsnapshot %}
