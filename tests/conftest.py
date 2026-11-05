from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb
import pytest

from train_elt.settings import Paths

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_DATE = date(2026, 11, 4)
METADATA_DATE = date(2026, 11, 5)


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_trains() -> list[dict]:
    return json.loads(fixture_bytes(f"trains_{FIXTURE_DATE}.json"))


class FixtureClient:
    """Stands in for DigitrafficClient, serving recorded API responses."""

    base_url = "https://rata.digitraffic.fi/api/v1"

    def __init__(self, trains: list[dict] | None = None) -> None:
        trains_body = (
            json.dumps(trains).encode()
            if trains is not None
            else fixture_bytes(f"trains_{FIXTURE_DATE}.json")
        )
        self.responses = {
            f"/trains/{FIXTURE_DATE}": trains_body,
            "/metadata/stations": fixture_bytes("stations.json"),
            "/metadata/cause-category-codes": fixture_bytes("cause_categories.json"),
        }
        self.calls: list[str] = []

    def get(self, path: str) -> bytes:
        self.calls.append(path)
        return self.responses[path]


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(tmp_path / "data")


def query(paths: Paths, sql: str, params: list | None = None) -> list[tuple]:
    """Open, query and close, so dbt can take the database file afterwards."""
    con = duckdb.connect(str(paths.warehouse_path), read_only=True)
    try:
        return con.execute(sql, params or []).fetchall()
    finally:
        con.close()
