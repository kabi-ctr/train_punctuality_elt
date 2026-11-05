-- Every passenger train run must have timetable rows and a scheduled final arrival.
-- (Shunting and locomotive moves can legitimately lack an arrival row.)

select train_run_id, timetable_rows, scheduled_arrival_local
from {{ ref('fct_train_runs') }}
where is_passenger_train
  and (timetable_rows = 0 or scheduled_arrival_local is null)
