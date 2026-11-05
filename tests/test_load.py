from __future__ import annotations

import pytest
from conftest import FIXTURE_DATE, METADATA_DATE, FixtureClient, fixture_trains, query

from train_elt import extract, load


def _land(paths, trains=None, force=False):
    client = FixtureClient(trains)
    extract.extract_metadata(client, paths, fetched_date=METADATA_DATE, force=force)
    extract.extract_trains(client, paths, FIXTURE_DATE, force=force)


def test_load_creates_one_raw_row_per_train(paths):
    _land(paths)
    summary = load.load_all(paths)

    assert (summary.partitions_loaded, summary.trains_loaded) == (1, 7)
    assert query(paths, "SELECT count(*) FROM raw.trains") == [(7,)]
    assert query(paths, "SELECT count(*) FROM raw.stations") == [(29,)]
    assert query(paths, "SELECT count(*) FROM raw.cause_categories") == [(15,)]
    rows = query(paths, "SELECT DISTINCT departure_date::VARCHAR FROM raw.trains")
    assert rows == [(str(FIXTURE_DATE),)]


def test_reloading_unchanged_files_is_a_no_op(paths):
    _land(paths)
    load.load_all(paths)
    second = load.load_all(paths)

    assert (second.partitions_loaded, second.partitions_skipped) == (0, 1)
    assert second.snapshots_loaded == 0
    assert query(paths, "SELECT count(*) FROM raw.trains") == [(7,)]


def test_changed_day_replaces_the_whole_partition(paths):
    _land(paths)
    load.load_all(paths)

    corrected = [t for t in fixture_trains() if t["trainNumber"] != 5452]
    _land(paths, corrected, force=True)
    summary = load.load_all(paths)

    assert summary.partitions_loaded == 1
    assert query(paths, "SELECT count(*) FROM raw.trains") == [(6,)]
    assert query(paths, "SELECT count(*) FROM raw.load_log WHERE target_table = 'raw.trains'") == [
        (2,)
    ]


def test_load_requires_metadata(paths):
    extract.extract_trains(FixtureClient(), paths, FIXTURE_DATE)
    with pytest.raises(load.LoadError, match="no stations snapshot"):
        load.load_all(paths)


def test_load_of_missing_date_fails_loudly(paths):
    _land(paths)
    with pytest.raises(load.LoadError, match="not landed yet"):
        load.load_all(paths, dates=[FIXTURE_DATE.replace(day=5)])
