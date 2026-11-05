-- Daily punctuality per category and per service group (commuter line letter or
-- long-distance train type). Rows with service_group = 'All' are category totals.

with runs as (

    select * from {{ ref('fct_train_runs') }}
    where is_passenger_train

)

select
    departure_date,
    train_category,
    case when grouping(service_group) = 1 then 'All' else service_group end as service_group,
    count(*)                                                        as trains_scheduled,
    count(*) filter (where is_cancelled)                            as trains_cancelled,
    count(*) filter (where is_punctuality_measured)                 as trains_measured,
    count(*) filter (where is_on_time)                              as trains_on_time,
    round(
        100.0 * count(*) filter (where is_on_time)
        / nullif(count(*) filter (where is_punctuality_measured), 0), 1
    )                                                               as punctuality_pct,
    round(avg(arrival_delay_minutes) filter (where is_punctuality_measured), 2)
                                                                    as avg_arrival_delay_minutes,
    quantile_cont(arrival_delay_minutes, 0.9) filter (where is_punctuality_measured)
                                                                    as p90_arrival_delay_minutes,
    max(arrival_delay_minutes) filter (where is_punctuality_measured)
                                                                    as max_arrival_delay_minutes

from runs
group by grouping sets (
    (departure_date, train_category, service_group),
    (departure_date, train_category)
)
