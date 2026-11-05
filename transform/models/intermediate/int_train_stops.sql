-- Timetable rows enriched with train attributes, local times and delays.

with timetable_rows as (

    select * from {{ ref('stg_digitraffic__timetable_rows') }}

),

trains as (

    select * from {{ ref('stg_digitraffic__trains') }}

)

select
    r.timetable_row_id,
    r.train_run_id,
    r.departure_date,
    r.train_number,
    r.row_index,
    t.train_category,
    t.train_type,
    t.commuter_line_id,
    t.operator_code,
    t.train_category in {{ sql_list(var('passenger_train_categories')) }} as is_passenger_train,
    r.station_code,
    r.stop_type,
    r.is_train_stopping,
    r.is_commercial_stop,
    r.is_cancelled,
    r.commercial_track,
    r.scheduled_at_utc,
    r.actual_at_utc,
    {{ helsinki_time('r.scheduled_at_utc') }}                              as scheduled_at_local,
    {{ helsinki_time('r.actual_at_utc') }}                                 as actual_at_local,
    -- Delays exist only where the train was actually seen; estimates are ignored.
    date_diff('second', r.scheduled_at_utc, r.actual_at_utc)               as delay_seconds,
    case when r.actual_at_utc is not null then r.source_difference_minutes end
                                                                           as delay_minutes,
    r.cause_count,
    greatest(r._loaded_at, t._loaded_at)                                   as _loaded_at

from timetable_rows as r
inner join trains as t
    on r.train_run_id = t.train_run_id
