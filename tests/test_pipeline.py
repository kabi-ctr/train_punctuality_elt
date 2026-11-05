"""End-to-end: recorded Digitraffic responses -> extract -> load -> dbt build -> marts.

Expected values were worked out by hand from tests/fixtures/trains_2026-11-04.json,
seven real trains from 4 November 2026.
"""

from __future__ import annotations

from datetime import datetime

import duckdb
import pytest
from conftest import FIXTURE_DATE, METADATA_DATE, FixtureClient, fixture_trains, query

from train_elt import extract, load, report, transform
from train_elt.settings import Paths


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Paths:
    paths = Paths(tmp_path_factory.mktemp("e2e") / "data")
    client = FixtureClient()
    extract.extract_metadata(client, paths, fetched_date=METADATA_DATE)
    extract.extract_trains(client, paths, FIXTURE_DATE)
    load.load_all(paths)
    transform.build(paths)  # runs every model, data test and unit test
    return paths


def test_every_train_becomes_one_run(built):
    assert query(
        built,
        "SELECT count(*), count(*) FILTER (WHERE is_passenger_train) FROM marts.fct_train_runs",
    ) == [(7, 6)]


def test_on_time_classification_per_train(built):
    rows = dict(query(built, "SELECT train_number, is_on_time FROM marts.fct_train_runs"))
    assert rows == {
        442: False,  # Vaasa -> Seinäjoki, long-distance, 6 min late (limit 5)
        445: True,  # Seinäjoki -> Vaasa, 1 min early
        1604: True,  # commuter H, 2 min late (limit 3)
        1706: True,  # commuter M, 1 min late
        10142: True,  # commuter V, exactly 3 min late
        1714: None,  # cancelled: not measured
        5452: None,  # cargo: not a passenger train
    }


def test_times_are_converted_to_helsinki(built):
    # Train 10142 left Riihimäki at 23:19 UTC on 3 Nov, which is 01:19 on 4 Nov in
    # Helsinki, so it belongs to the 4 Nov service day.
    [(departure, service_date)] = query(
        built,
        "SELECT scheduled_departure_local, departure_date::VARCHAR "
        "FROM marts.fct_train_runs WHERE train_number = 10142",
    )
    assert departure == datetime(2026, 11, 4, 1, 19)
    assert service_date == "2026-11-04"


def test_daily_punctuality_totals(built):
    rows = query(
        built,
        """
        SELECT train_category, trains_scheduled, trains_cancelled, trains_measured,
               trains_on_time, punctuality_pct
        FROM marts.mart_daily_punctuality
        WHERE service_group = 'All' ORDER BY train_category
        """,
    )
    assert rows == [
        ("Commuter", 4, 1, 3, 3, 100.0),
        ("Long-distance", 2, 0, 2, 1, 50.0),
    ]


def test_delay_causes_are_labelled(built):
    rows = query(
        built,
        "SELECT category_code, category_label_en, cause_reports, trains_affected "
        "FROM marts.mart_delay_causes",
    )
    assert rows == [("L", "Traffic control", 3, 3)]


def test_station_departure_delays(built):
    [(measured, late, avg_delay)] = query(
        built,
        "SELECT departures_measured, departures_late, avg_departure_delay_minutes "
        "FROM marts.mart_station_daily WHERE station_code = 'SK'",
    )
    # Train 445 left Seinäjoki 8 minutes late.
    assert (measured, late, avg_delay) == (1, 1, 8.0)


def test_report_and_parquet_export(built, tmp_path):
    text = report.markdown_report(built, min_departures=1)
    assert "Finnish passenger train punctuality, 2026-11-04" in text
    assert "Traffic control" in text

    files = report.export_parquet(built, tmp_path / "exports")
    assert len(files) == 6
    [(count,)] = duckdb.sql(
        f"SELECT count(*) FROM '{(tmp_path / 'exports' / 'fct_train_runs.parquet').as_posix()}'"
    ).fetchall()
    assert count == 7


def test_incremental_build_picks_up_a_corrected_day(built):
    # Digitraffic corrects past days; simulate train 442 being re-reported as on time.
    trains = fixture_trains()
    final_row = next(t for t in trains if t["trainNumber"] == 442)["timeTableRows"][-1]
    final_row["actualTime"] = "2026-11-04T16:58:00.000Z"
    final_row["differenceInMinutes"] = 1

    extract.extract_trains(FixtureClient(trains), built, FIXTURE_DATE, force=True)
    load.load_all(built)
    transform.build(built)  # incremental: only the reloaded partition is rebuilt

    assert query(built, "SELECT count(*) FROM marts.fct_train_runs") == [(7,)]
    assert query(built, "SELECT is_on_time FROM marts.fct_train_runs WHERE train_number = 442") == [
        (True,)
    ]
    assert query(
        built,
        "SELECT punctuality_pct FROM marts.mart_daily_punctuality "
        "WHERE service_group = 'All' AND train_category = 'Long-distance'",
    ) == [(100.0,)]
