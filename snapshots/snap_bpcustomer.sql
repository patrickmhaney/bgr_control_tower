{% snapshot snap_bpcustomer %}
    select * from {{ ref('stg_sage_x3__bpcustomer') }}
{% endsnapshot %}
