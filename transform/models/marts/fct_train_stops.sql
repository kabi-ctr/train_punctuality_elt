-- Fact table: one row per commercial stop event (passenger-facing arrival or
-- departure). Incremental on the raw load timestamp, like fct_train_runs.

{{
    config(
        materialized='incremental',
        unique_key='timetable_row_id',
        incremental_strategy='delete+insert',
    )
}}

select
    timetable_row_id,
    train_run_id,
    departure_date,
    train_number,
    row_index,
    train_category,
    train_type,
    commuter_line_id,
    is_passenger_train,
    station_code,
    stop_type,
    is_cancelled,
    commercial_track,
    scheduled_at_local,
    actual_at_local,
    hour(scheduled_at_local)    as scheduled_hour_local,
    delay_seconds,
    delay_minutes,
    cause_count,
    _loaded_at

from {{ ref('int_train_stops') }}
where is_commercial_stop

{% if is_incremental() %}
    and _loaded_at > (select coalesce(max(_loaded_at), '1900-01-01'::timestamp) from {{ this }})
{% endif %}
