-- Fact table: one row per train run. Incremental on the raw load timestamp, so a
-- reloaded (corrected) day replaces its rows without rebuilding history.

{{
    config(
        materialized='incremental',
        unique_key='train_run_id',
        incremental_strategy='delete+insert',
    )
}}

select * from {{ ref('int_train_runs') }}

{% if is_incremental() %}
where _loaded_at > (select coalesce(max(_loaded_at), '1900-01-01'::timestamp) from {{ this }})
{% endif %}
