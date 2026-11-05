select
    payload ->> '$.categoryCode'             as category_code,
    payload ->> '$.categoryName'             as category_name_fi,
    (payload ->> '$.validFrom')::date        as valid_from,
    (payload ->> '$.validTo')::date          as valid_to

from {{ source('digitraffic', 'cause_categories') }}
