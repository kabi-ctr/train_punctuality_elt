-- A recorded stop more than a day early or late almost certainly means a parsing
-- or timezone bug, not a real train. Warn rather than fail on real-world outliers.

{{ config(severity='warn') }}

select timetable_row_id, departure_date, station_code, delay_seconds
from {{ ref('fct_train_stops') }}
where abs(delay_seconds) > 24 * 60 * 60
