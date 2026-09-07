{% snapshot snap_netstock_item_location %}
    select * from {{ ref('stg_netstock__item_location') }}
{% endsnapshot %}
