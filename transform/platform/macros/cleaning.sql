{#- Cleaning helpers used by every staging model. Both are portable SQL. -#}

{% macro clean_str(column) -%}
    {#- Trim CHAR padding and turn empty strings into nulls. X3 pads keys to
        their column width on the source side, so they arrive padded. -#}
    nullif(trim({{ column }}), '')
{%- endmacro %}


{% macro x3_date(column) -%}
    {#- X3 on SQL Server writes 1753-01-01 to mean "no date". -#}
    nullif({{ column }}, cast('{{ var("x3_null_date") }}' as date))
{%- endmacro %}


{% macro flag(condition) -%}
    {#- A 0/1 integer flag. Gold uses integers, not booleans: they sum, they
        slice, and T-SQL has no boolean type to port them to. -#}
    case when {{ condition }} then 1 else 0 end
{%- endmacro %}
