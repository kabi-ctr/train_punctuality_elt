-- Daily count of reported delay causes on passenger trains, by top-level category.

with causes as (

    select * from {{ ref('stg_digitraffic__delay_causes') }}

),

passenger_runs as (

    select train_run_id from {{ ref('fct_train_runs') }}
    where is_passenger_train

)

select
    c.departure_date,
    c.category_code,
    cc.category_name_fi,
    labels.label_en                         as category_label_en,
    count(*)                                as cause_reports,
    count(distinct c.train_run_id)          as trains_affected

from causes as c
inner join passenger_runs as r
    on c.train_run_id = r.train_run_id
left join {{ ref('stg_digitraffic__cause_categories') }} as cc
    on c.category_code = cc.category_code
left join {{ ref('cause_category_labels') }} as labels
    on c.category_code = labels.category_code
group by all
