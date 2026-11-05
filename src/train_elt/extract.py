"""Extract: download Digitraffic responses into a dated landing zone.

Each response is stored unchanged (gzipped) with a manifest next to it, so the
load step can be re-run at any time without calling the API again.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

from train_elt.settings import (
    DIGITRAFFIC_BASE_URL,
    DIGITRAFFIC_USER,
    METADATA_ENDPOINTS,
    Paths,
    helsinki_today,
    manifest_path,
)

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ExtractError(RuntimeError):
    """The API could not be reached or returned something unusable."""


class JsonSource(Protocol):
    base_url: str

    def get(self, path: str) -> bytes: ...


@dataclass
class DigitrafficClient:
    """Minimal HTTP client with retries and exponential backoff (stdlib only)."""

    base_url: str = DIGITRAFFIC_BASE_URL
    user: str = DIGITRAFFIC_USER
    timeout_seconds: float = 120.0
    max_retries: int = 4
    backoff_seconds: float = 2.0
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)

    def get(self, path: str) -> bytes:
        url = f"{self.base_url}{path}"
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "Digitraffic-User": self.user,
        }
        for attempt in range(self.max_retries + 1):
            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    body = response.read()
                    if response.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                    return body
            except urllib.error.HTTPError as exc:
                if exc.code not in RETRYABLE_STATUS or attempt == self.max_retries:
                    raise ExtractError(f"GET {url} failed with HTTP {exc.code}") from exc
                delay = self._retry_after(exc) or self.backoff_seconds * 2**attempt
                log.warning("GET %s -> HTTP %s, retrying in %.1fs", url, exc.code, delay)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt == self.max_retries:
                    raise ExtractError(f"GET {url} failed: {exc}") from exc
                delay = self.backoff_seconds * 2**attempt
                log.warning("GET %s failed (%s), retrying in %.1fs", url, exc, delay)
            self.sleep(delay)
        raise AssertionError("unreachable")

    @staticmethod
    def _retry_after(exc: urllib.error.HTTPError) -> float | None:
        value = exc.headers.get("Retry-After") if exc.headers else None
        try:
            return float(value) if value is not None else None
        except ValueError:
            return None


@dataclass(frozen=True)
class LandingResult:
    path: Path
    records: int
    skipped: bool


def write_landing(path: Path, body: bytes, source_url: str, records: int) -> None:
    """Write payload + manifest atomically (temp file, then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wb") as fh:
        fh.write(body)
    tmp.replace(path)
    manifest = {
        "source_url": source_url,
        "extracted_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "records": records,
        "sha256": hashlib.sha256(body).hexdigest(),
        "uncompressed_bytes": len(body),
    }
    manifest_path(path).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def read_manifest(path: Path) -> dict:
    return json.loads(manifest_path(path).read_text(encoding="utf-8"))


def _parse_array(body: bytes, what: str) -> list[dict]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ExtractError(f"{what}: response is not valid JSON") from exc
    if not isinstance(data, list):
        raise ExtractError(f"{what}: expected a JSON array, got {type(data).__name__}")
    return data


def validate_trains(trains: list[dict], departure_date: date) -> None:
    """Reject responses that would silently corrupt the partition."""
    expected = departure_date.isoformat()
    for train in trains:
        if train.get("departureDate") != expected:
            raise ExtractError(
                f"train {train.get('trainNumber')} has departureDate "
                f"{train.get('departureDate')}, expected {expected}"
            )
        if not isinstance(train.get("trainNumber"), int):
            raise ExtractError(f"train without an integer trainNumber on {expected}")
        if not isinstance(train.get("timeTableRows"), list):
            raise ExtractError(f"train {train['trainNumber']} has no timeTableRows list")


def extract_trains(
    client: JsonSource, paths: Paths, departure_date: date, force: bool = False
) -> LandingResult:
    """Land every train that ran on one departure date (Finnish service date)."""
    target = paths.trains_file(departure_date)
    if target.exists() and not force:
        log.info("trains %s already landed, skipping", departure_date)
        return LandingResult(target, read_manifest(target)["records"], skipped=True)

    api_path = f"/trains/{departure_date.isoformat()}"
    body = client.get(api_path)
    trains = _parse_array(body, f"trains {departure_date}")
    validate_trains(trains, departure_date)
    write_landing(target, body, client.base_url + api_path, len(trains))
    log.info("landed %d trains for %s", len(trains), departure_date)
    return LandingResult(target, len(trains), skipped=False)


def extract_metadata(
    client: JsonSource, paths: Paths, fetched_date: date | None = None, force: bool = False
) -> dict[str, LandingResult]:
    """Land the station and delay-cause reference lists (one snapshot per day)."""
    fetched_date = fetched_date or helsinki_today()
    results = {}
    for name, api_path in METADATA_ENDPOINTS.items():
        target = paths.metadata_file(name, fetched_date)
        if target.exists() and not force:
            results[name] = LandingResult(target, read_manifest(target)["records"], skipped=True)
            continue
        body = client.get(api_path)
        records = _parse_array(body, name)
        if not records:
            raise ExtractError(f"{name}: empty response")
        write_landing(target, body, client.base_url + api_path, len(records))
        results[name] = LandingResult(target, len(records), skipped=False)
        log.info("landed %d %s", len(records), name)
    return results
