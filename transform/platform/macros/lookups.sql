{#- Resolve a source key to its golden key through MDM contract C3, and
    convert amounts with the GL-derived rate. Each lookup renames its columns
    inside a derived table so an outer column with the same name can never be
    captured by the subquery. -#}

{% macro customer_key(source_system, column) -%}
    coalesce((select x.ck from (select source_system as ss, source_key as sk, customer_key as ck
                                from {{ ref('conf_customer_xref') }}) as x
              where x.ss = '{{ source_system }}' and x.sk = {{ column }}),
             'UNKNOWN')
{%- endmacro %}

{% macro employee_key(column, source_system='sage_x3.AUTILIS') -%}
    coalesce((select x.ek from (select source_system as ss, source_key as sk, employee_key as ek
                                from {{ ref('conf_employee_xref') }}) as x
              where x.ss = '{{ source_system }}' and x.sk = {{ column }}),
             'E-UNKNOWN')
{%- endmacro %}

{% macro to_usd(amount, currency, on_date) -%}
    {{ amount }} * coalesce(
        (select r.fx from (select currency_code as cur, rate_month as mon,
                                  rate_to_reporting_currency as fx
                           from {{ ref('int_fx_rate') }}) as r
         where r.cur = {{ currency }}
           and r.mon = cast({{ dbt.date_trunc('month', on_date) }} as date)),
        (select max(r.fb) from (select currency_code as cur, fallback_rate as fb
                                from {{ ref('int_fx_rate') }}) as r
         where r.cur = {{ currency }}),
        1.0)
{%- endmacro %}

{% macro date_part(part, date) -%}
    {{ return(adapter.dispatch('date_part', 'platform')(part, date)) }}
{%- endmacro %}

{% macro default__date_part(part, date) -%}
    {#- ANSI EXTRACT. sqlglot turns it into DATEPART for T-SQL. -#}
    extract({{ part }} from {{ date }})
{%- endmacro %}
