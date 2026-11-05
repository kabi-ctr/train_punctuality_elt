select
    payload ->> '$.stationShortCode'               as station_code,
    (payload ->> '$.stationUICCode')::integer      as station_uic_code,
    payload ->> '$.stationName'                    as station_name,
    payload ->> '$.type'                           as station_type,
    (payload ->> '$.passengerTraffic')::boolean    as has_passenger_traffic,
    payload ->> '$.countryCode'                    as country_code,
    (payload ->> '$.latitude')::double             as latitude,
    (payload ->> '$.longitude')::double            as longitude

from {{ source('digitraffic', 'stations') }}
