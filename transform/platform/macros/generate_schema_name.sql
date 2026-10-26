{#- Use the configured schema name as is (bronze, silver, gold, seed), not
    dbt's default of prefixing it with the target schema. The layer names are
    what people query, so they should read the same in every environment.

    It is the dispatched default, so every pack picks it up through the
    `dispatch` search order in its (templated) dbt_project.yml. -#}
{% macro default__generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name if custom_schema_name is not none else target.schema }}
{%- endmacro %}
