{# Convert a naive UTC timestamp to naive Europe/Helsinki local time (DST-aware). #}
{% macro helsinki_time(utc_timestamp) -%}
    timezone('Europe/Helsinki', timezone('UTC', {{ utc_timestamp }}))
{%- endmacro %}

{# Render a SQL list literal from a dbt var, e.g. ('Commuter', 'Long-distance'). #}
{% macro sql_list(values) -%}
    ({%- for value in values -%}'{{ value }}'{%- if not loop.last -%}, {% endif -%}{%- endfor -%})
{%- endmacro %}
