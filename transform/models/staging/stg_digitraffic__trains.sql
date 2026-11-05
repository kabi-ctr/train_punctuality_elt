-- One row per train run: the train-level attributes of the API payload.

with source as (

    select * from {{ source('digitraffic', 'trains') }}

)

select
    concat(departure_date, '_', train_number)       as train_run_id,
    departure_date,
    train_number,
    payload ->> '$.operatorShortCode'                as operator_code,
    payload ->> '$.trainCategory'                    as train_category,
    payload ->> '$.trainType'                        as train_type,
    nullif(payload ->> '$.commuterLineID', '')       as commuter_line_id,
    (payload ->> '$.cancelled')::boolean             as is_cancelled,
    payload ->> '$.timetableType'                    as timetable_type,
    source_version,
    _loaded_at

from source
