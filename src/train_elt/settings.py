"""Paths and constants shared by every pipeline step."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

DIGITRAFFIC_BASE_URL = "https://rata.digitraffic.fi/api/v1"
# Digitraffic asks API clients to identify themselves with this header.
DIGITRAFFIC_USER = "train-punctuality-elt/0.1 (github.com/kabi-ctr/train_punctuality_elt)"

HELSINKI = ZoneInfo("Europe/Helsinki")

# Repository root: src/train_elt/settings.py -> parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DBT_PROJECT_DIR = PROJECT_ROOT / "transform"

METADATA_ENDPOINTS = {
    "stations": "/metadata/stations",
    "cause_categories": "/metadata/cause-category-codes",
}


@dataclass(frozen=True)
class Paths:
    """Where landing files, the warehouse and exports live."""

    data_dir: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_dir", Path(self.data_dir))

    @classmethod
    def from_env(cls, data_dir: str | Path | None = None) -> Paths:
        return cls(Path(data_dir or os.environ.get("TRAIN_ELT_DATA_DIR", "data")))

    @property
    def landing_dir(self) -> Path:
        return self.data_dir / "landing" / "digitraffic"

    @property
    def trains_landing_dir(self) -> Path:
        return self.landing_dir / "trains"

    @property
    def warehouse_path(self) -> Path:
        return self.data_dir / "warehouse" / "trains.duckdb"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    def trains_file(self, departure_date: date) -> Path:
        partition = f"departure_date={departure_date.isoformat()}"
        return self.trains_landing_dir / partition / "trains.json.gz"

    def metadata_file(self, name: str, fetched_date: date) -> Path:
        partition = f"fetched_date={fetched_date.isoformat()}"
        return self.landing_dir / "metadata" / name / partition / f"{name}.json.gz"


def manifest_path(payload_path: Path) -> Path:
    """Every landing file has a JSON manifest next to it."""
    return payload_path.with_name("_manifest.json")


def helsinki_today() -> date:
    return datetime.now(HELSINKI).date()


def completed_days(days: int, end: date | None = None) -> list[date]:
    """The last `days` service days, ending yesterday in Helsinki time by default.

    Today's trains are still running, so the newest complete day is yesterday.
    """
    if days < 1:
        raise ValueError("days must be at least 1")
    last = end or helsinki_today() - timedelta(days=1)
    return [last - timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def date_range(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError(f"end date {end} is before start date {start}")
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]
