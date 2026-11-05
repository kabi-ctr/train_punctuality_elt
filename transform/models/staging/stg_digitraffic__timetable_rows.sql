-- One row per timetable row: every scheduled arrival or departure of a train
-- at a station, including stations it passes without stopping.

with source as (

    select departure_date, train_number, payload, _loaded_at
    from {{ source('digitraffic', 'trains') }}

),

row_lists as (

    select
        concat(departure_date, '_', train_number)        as train_run_id,
        departure_date,
        train_number,
        json_extract(payload, '$.timeTableRows[*]')      as timetable_rows,
        _loaded_at
    from source

),

exploded as (

    -- Two unnests of equal length in one SELECT are zipped together, so the
    -- generated index keeps the API's row order.
    select
        train_run_id,
        departure_date,
        train_number,
        unnest(generate_series(1, len(timetable_rows)))  as row_index,
        unnest(timetable_rows)                           as r,
        _loaded_at
    from row_lists

)

select
    concat(train_run_id, '_', row_index)                            as timetable_row_id,
    train_run_id,
    departure_date,
    train_number,
    row_index,
    r ->> '$.stationShortCode'                                       as station_code,
    r ->> '$.type'                                                   as stop_type,
    (r ->> '$.trainStopping')::boolean                               as is_train_stopping,
    coalesce((r ->> '$.commercialStop')::boolean, false)             as is_commercial_stop,
    nullif(r ->> '$.commercialTrack', '')                            as commercial_track,
    (r ->> '$.cancelled')::boolean                                   as is_cancelled,
    timezone('UTC', (r ->> '$.scheduledTime')::timestamptz)          as scheduled_at_utc,
    timezone('UTC', (r ->> '$.actualTime')::timestamptz)             as actual_at_utc,
    timezone('UTC', (r ->> '$.liveEstimateTime')::timestamptz)       as estimated_at_utc,
    -- Digitraffic's own whole-minute delay (rounded half up). Present for
    -- estimates too, so only trust it when actual_at_utc is set.
    (r ->> '$.differenceInMinutes')::integer                         as source_difference_minutes,
    coalesce(json_array_length(r, '$.causes'), 0)                    as cause_count,
    json_extract(r, '$.causes')                                      as causes,
    _loaded_at

from exploded
