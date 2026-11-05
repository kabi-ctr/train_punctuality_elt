-- Every row must satisfy: on time <= measured <= scheduled - cancelled,
-- and the percentage must lie between 0 and 100. Returns violating rows.

select *
from {{ ref('mart_daily_punctuality') }}
where trains_on_time > trains_measured
   or trains_measured > trains_scheduled - trains_cancelled
   or punctuality_pct < 0
   or punctuality_pct > 100
