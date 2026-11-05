-- One row per delay cause reported on a timetable row (a row can have several).

with rows_with_causes as (

    select
        timetable_row_id,
        train_run_id,
        departure_date,
        station_code,
        stop_type,
        json_extract(causes, '$[*]') as cause_list,
        _loaded_at
    from {{ ref('stg_digitraffic__timetable_rows') }}
    where cause_count > 0

),

exploded as (

    select
        timetable_row_id,
        train_run_id,
        departure_date,
        station_code,
        stop_type,
        unnest(generate_series(1, len(cause_list))) as cause_index,
        unnest(cause_list)                          as c,
        _loaded_at
    from rows_with_causes

)

select
    concat(timetable_row_id, '_', cause_index)  as delay_cause_id,
    timetable_row_id,
    train_run_id,
    departure_date,
    station_code,
    stop_type,
    cause_index,
    c ->> '$.categoryCode'                      as category_code,
    c ->> '$.detailedCategoryCode'              as detailed_category_code,
    c ->> '$.thirdCategoryCode'                 as third_category_code,
    _loaded_at

from exploded
