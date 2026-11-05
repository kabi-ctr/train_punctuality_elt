-- One row per train run with its origin, destination, final-arrival delay and
-- on-time classification.

{% set thresholds = var('on_time_threshold_minutes') %}

with stops as (

    select * from {{ ref('int_train_stops') }}

),

trains as (

    select * from {{ ref('stg_digitraffic__trains') }}

),

first_departure as (

    select *
    from stops
    where stop_type = 'DEPARTURE'
    qualify row_number() over (partition by train_run_id order by row_index) = 1

),

final_arrival as (

    select *
    from stops
    where stop_type = 'ARRIVAL'
    qualify row_number() over (partition by train_run_id order by row_index desc) = 1

),

row_stats as (

    select
        train_run_id,
        count(*)                                                        as timetable_rows,
        count(*) filter (where is_commercial_stop)                      as commercial_stop_rows,
        count(*) filter (where is_cancelled)                            as cancelled_rows,
        max(delay_minutes) filter (where is_commercial_stop)            as max_stop_delay_minutes
    from stops
    group by train_run_id

),

runs as (

    select
        t.train_run_id,
        t.departure_date,
        t.train_number,
        t.train_category,
        t.train_type,
        t.commuter_line_id,
        -- Commuter trains are grouped by line letter, long-distance by train type.
        coalesce(t.commuter_line_id, t.train_type)                      as service_group,
        t.operator_code,
        t.train_category in {{ sql_list(var('passenger_train_categories')) }}
                                                                        as is_passenger_train,
        t.is_cancelled,
        not t.is_cancelled and coalesce(s.cancelled_rows, 0) > 0        as is_partially_cancelled,
        d.station_code                                                  as origin_station_code,
        a.station_code                                                  as destination_station_code,
        d.scheduled_at_local                                            as scheduled_departure_local,
        a.scheduled_at_local                                            as scheduled_arrival_local,
        d.actual_at_local                                               as actual_departure_local,
        a.actual_at_local                                               as actual_arrival_local,
        d.delay_minutes                                                 as departure_delay_minutes,
        a.delay_minutes                                                 as arrival_delay_minutes,
        a.delay_seconds                                                 as arrival_delay_seconds,
        s.max_stop_delay_minutes,
        coalesce(s.timetable_rows, 0)                                   as timetable_rows,
        coalesce(s.commercial_stop_rows, 0)                             as commercial_stop_rows,
        case t.train_category
            {%- for category, minutes in thresholds.items() %}
            when '{{ category }}' then {{ minutes }}
            {%- endfor %}
        end                                                             as on_time_threshold_minutes,
        t._loaded_at
    from trains as t
    left join row_stats as s on t.train_run_id = s.train_run_id
    left join first_departure as d on t.train_run_id = d.train_run_id
    left join final_arrival as a on t.train_run_id = a.train_run_id

)

select
    *,
    -- Measurable: ran, has a threshold, and its final arrival was actually recorded.
    not is_cancelled
        and on_time_threshold_minutes is not null
        and arrival_delay_minutes is not null                           as is_punctuality_measured,
    case
        when not is_cancelled
            and on_time_threshold_minutes is not null
            and arrival_delay_minutes is not null
        then arrival_delay_minutes <= on_time_threshold_minutes
    end                                                                 as is_on_time

from runs
