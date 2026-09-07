{#
    Normalisation helpers for entity resolution.

    These live in macros rather than inline because the same normalisation has
    to be applied identically to both sides of every match. A subtle difference
    between the two sides of a join is the classic way an entity resolution
    model quietly loses rows, and it is invisible in review when the two
    expressions are 40 lines apart.
#}

{% macro name_upper(column) -%}
    upper(trim({{ column }}))
{%- endmacro %}


{% macro name_alnum(column) -%}
    {#- Punctuation- and space-insensitive. Legal suffix retained, so
        "Halcyon Hydraulics, LLC" and "Halcyon Hydraulics LLC" collapse but
        "Redstone Machine Works LLC" and "Redstone Machine Works Inc" do not. -#}
    upper(regexp_replace({{ column }}, '[^a-zA-Z0-9]', '', 'g'))
{%- endmacro %}


{% macro legal_suffix_pattern() -%}
    {#- The alternation, built from seeds/legal_suffix.csv at compile time.

        A seed rather than an inline regex because entity resolution is the one
        thing a client iterates on hardest once real names arrive, and every
        other business-tunable list in this project is a seed or a var. Falls
        back to the original inline list when the seed has not been loaded, so
        the macro still compiles on a clean checkout - `dbt parse` runs before
        `dbt seed` on a first build. -#}
    {%- set fallback = 'INC|LLC|LTD|CORP|CO|GROUP|COMPANY|ULC' -%}
    {%- if execute -%}
        {%- set relation = ref('legal_suffix') -%}
        {%- set result = run_query(
            "select suffix from " ~ relation ~ " order by length(suffix) desc, suffix"
        ) -%}
        {%- if result and result.rows | length > 0 -%}
            {{- result.columns[0].values() | join('|') -}}
        {%- else -%}
            {{- fallback -}}
        {%- endif -%}
    {%- else -%}
        {{- fallback -}}
    {%- endif -%}
{%- endmacro %}


{% macro name_core(column) -%}
    {#- Legal suffix stripped as well. Higher recall, lower precision: this is
        the tier that generates ambiguity, because two legally distinct
        entities can share a core name. -#}
    upper(
        regexp_replace(
            regexp_replace(
                regexp_replace({{ column }}, '[^a-zA-Z0-9 ]', '', 'g'),
                '\s+({{ bgr_control_tower.legal_suffix_pattern() }})$', '', 'i'
            ),
            '\s+', ' ', 'g'
        )
    )
{%- endmacro %}


{% macro domain_stem(column) -%}
    {#- HubSpot domains here are the company name lower-cased, stripped of
        non-alphanumerics and truncated to 18 characters, plus a TLD. That
        makes the stem a usable prefix probe against the ERP name. -#}
    upper(regexp_replace({{ column }}, '\..*$', ''))
{%- endmacro %}


{% macro person_key(last_name, first_name) -%}
    {#- X3 REPRESENT.REPNAM_0 is "LASTNAME FIRSTNAME". Paycom is two columns.
        This macro is what makes the two comparable. -#}
    upper(trim({{ last_name }}) || ' ' || trim({{ first_name }}))
{%- endmacro %}
