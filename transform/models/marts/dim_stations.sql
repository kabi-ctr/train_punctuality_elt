select
    station_code,
    station_uic_code,
    station_name,
    station_type,
    has_passenger_traffic,
    country_code,
    latitude,
    longitude

from {{ ref('stg_digitraffic__stations') }}
