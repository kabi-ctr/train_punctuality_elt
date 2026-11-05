-- The 'All' row of each day and category must equal the sum of its service groups.

with groups as (

    select departure_date, train_category,
           sum(trains_scheduled) as scheduled,
           sum(trains_measured)  as measured,
           sum(trains_on_time)   as on_time
    from {{ ref('mart_daily_punctuality') }}
    where service_group <> 'All'
    group by all

),

totals as (

    select departure_date, train_category,
           trains_scheduled as scheduled,
           trains_measured  as measured,
           trains_on_time   as on_time
    from {{ ref('mart_daily_punctuality') }}
    where service_group = 'All'

)

select *
from totals as t
full outer join groups as g using (departure_date, train_category)
where t.scheduled is distinct from g.scheduled
   or t.measured  is distinct from g.measured
   or t.on_time   is distinct from g.on_time
