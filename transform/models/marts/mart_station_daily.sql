-- Daily departure performance per station for passenger trains.

{% set late_after = var('late_departure_threshold_minutes') %}

with departures as (

    select * from {{ ref('fct_train_stops') }}
    where is_passenger_train and stop_type = 'DEPARTURE'

)

select
    d.departure_date,
    d.station_code,
    s.station_name,
    count(*)                                                            as departures_scheduled,
    count(*) filter (where d.is_cancelled)                              as departures_cancelled,
    count(*) filter (where d.delay_minutes is not null)                 as departures_measured,
    round(avg(d.delay_minutes), 2)                                      as avg_departure_delay_minutes,
    count(*) filter (where d.delay_minutes > {{ late_after }})          as departures_late,
    round(
        100.0 * count(*) filter (where d.delay_minutes > {{ late_after }})
        / nullif(count(*) filter (where d.delay_minutes is not null), 0), 1
    )                                                                   as pct_departures_late

from departures as d
left join {{ ref('dim_stations') }} as s
    on d.station_code = s.station_code
group by all
