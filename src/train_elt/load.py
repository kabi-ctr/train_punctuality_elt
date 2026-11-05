"""Load: copy landing files into DuckDB raw tables, one JSON object per row.

No transformation happens here (that is dbt's job). Loads are idempotent:
a train partition is replaced as a whole inside a transaction, and a file
whose checksum was already loaded is skipped.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from train_elt.extract import read_manifest
from train_elt.settings import METADATA_ENDPOINTS, Paths

log = logging.getLogger(__name__)

RAW_DDL = """
CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.trains (
    departure_date  DATE      NOT NULL,
    train_number    INTEGER   NOT NULL,
    source_version  BIGINT,
    payload         JSON      NOT NULL,
    _source_file    VARCHAR   NOT NULL,
    _source_sha256  VARCHAR   NOT NULL,
    _extracted_at   TIMESTAMP,
    _loaded_at      TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS raw.stations (
    payload        JSON      NOT NULL,
    _source_file   VARCHAR   NOT NULL,
    _extracted_at  TIMESTAMP,
    _loaded_at     TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS raw.cause_categories (
    payload        JSON      NOT NULL,
    _source_file   VARCHAR   NOT NULL,
    _extracted_at  TIMESTAMP,
    _loaded_at     TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS raw.load_log (
    target_table    VARCHAR   NOT NULL,
    partition_key   VARCHAR   NOT NULL,
    source_file     VARCHAR   NOT NULL,
    source_sha256   VARCHAR   NOT NULL,
    rows_loaded     BIGINT    NOT NULL,
    loaded_at       TIMESTAMP NOT NULL
);
"""

PARTITION_RE = re.compile(r"departure_date=(\d{4}-\d{2}-\d{2})$")


class LoadError(RuntimeError):
    pass


@dataclass
class LoadSummary:
    partitions_loaded: int = 0
    partitions_skipped: int = 0
    trains_loaded: int = 0
    snapshots_loaded: int = 0


def connect(paths: Paths) -> duckdb.DuckDBPyConnection:
    paths.warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(paths.warehouse_path))
    con.execute(RAW_DDL)
    return con


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _extracted_at(manifest: dict) -> datetime | None:
    value = manifest.get("extracted_at")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ") if value else None


def _already_loaded(con, table: str, partition: str, sha256: str) -> bool:
    row = con.execute(
        """
        SELECT source_sha256 FROM raw.load_log
        WHERE target_table = ? AND partition_key = ?
        ORDER BY loaded_at DESC LIMIT 1
        """,
        [table, partition],
    ).fetchone()
    return row is not None and row[0] == sha256


def load_trains_partition(con, path: Path, departure_date: date, force: bool = False) -> int | None:
    """Replace one departure_date partition. Returns rows loaded, or None if skipped."""
    manifest = read_manifest(path)
    partition = departure_date.isoformat()
    if not force and _already_loaded(con, "raw.trains", partition, manifest["sha256"]):
        log.info("raw.trains %s unchanged, skipping", partition)
        return None

    loaded_at = _utc_now()
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("DELETE FROM raw.trains WHERE departure_date = ?", [departure_date])
        con.execute(
            """
            INSERT INTO raw.trains
            SELECT
                (json ->> '$.departureDate')::DATE,
                (json ->> '$.trainNumber')::INTEGER,
                (json ->> '$.version')::BIGINT,
                json,
                $file, $sha, $extracted_at, $loaded_at
            FROM read_json_objects($file, format = 'array')
            """,
            {
                "file": str(path),
                "sha": manifest["sha256"],
                "extracted_at": _extracted_at(manifest),
                "loaded_at": loaded_at,
            },
        )
        rows, wrong_date = con.execute(
            """
            SELECT count(*), count(*) FILTER (WHERE departure_date <> ?)
            FROM raw.trains WHERE _loaded_at = ? AND _source_file = ?
            """,
            [departure_date, loaded_at, str(path)],
        ).fetchone()
        if wrong_date:
            raise LoadError(f"{path}: {wrong_date} trains outside partition {partition}")
        if rows != manifest["records"]:
            raise LoadError(f"{path}: loaded {rows} rows, manifest says {manifest['records']}")
        con.execute(
            "INSERT INTO raw.load_log VALUES ('raw.trains', ?, ?, ?, ?, ?)",
            [partition, str(path), manifest["sha256"], rows, loaded_at],
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    log.info("raw.trains %s: %d trains", partition, rows)
    return rows


def load_snapshot(con, table: str, path: Path, force: bool = False) -> bool:
    """Replace a reference table (stations, cause categories) with a newer snapshot."""
    manifest = read_manifest(path)
    target = f"raw.{table}"
    if not force and _already_loaded(con, target, "snapshot", manifest["sha256"]):
        return False
    loaded_at = _utc_now()
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"DELETE FROM {target}")
        con.execute(
            f"""
            INSERT INTO {target}
            SELECT json, $file, $extracted_at, $loaded_at
            FROM read_json_objects($file, format = 'array')
            """,
            {"file": str(path), "extracted_at": _extracted_at(manifest), "loaded_at": loaded_at},
        )
        rows = con.execute(f"SELECT count(*) FROM {target}").fetchone()[0]
        con.execute(
            "INSERT INTO raw.load_log VALUES (?, 'snapshot', ?, ?, ?, ?)",
            [target, str(path), manifest["sha256"], rows, loaded_at],
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    log.info("%s: %d rows", target, rows)
    return True


def landed_train_partitions(paths: Paths) -> dict[date, Path]:
    partitions = {}
    if not paths.trains_landing_dir.exists():
        return partitions
    for directory in sorted(paths.trains_landing_dir.iterdir()):
        match = PARTITION_RE.search(directory.name)
        payload = directory / "trains.json.gz"
        if match and payload.exists():
            partitions[date.fromisoformat(match.group(1))] = payload
    return partitions


def latest_snapshot(paths: Paths, name: str) -> Path | None:
    root = paths.landing_dir / "metadata" / name
    files = sorted(root.glob(f"fetched_date=*/{name}.json.gz")) if root.exists() else []
    return files[-1] if files else None


def load_all(paths: Paths, dates: list[date] | None = None, force: bool = False) -> LoadSummary:
    """Load every landed partition (or only `dates`) plus the newest metadata snapshots."""
    summary = LoadSummary()
    con = connect(paths)
    try:
        for name in METADATA_ENDPOINTS:
            snapshot = latest_snapshot(paths, name)
            if snapshot is None:
                raise LoadError(f"no {name} snapshot in {paths.landing_dir}; run extract first")
            summary.snapshots_loaded += load_snapshot(con, name, snapshot, force)

        partitions = landed_train_partitions(paths)
        if dates is not None:
            missing = sorted(set(dates) - set(partitions))
            if missing:
                raise LoadError(f"not landed yet: {', '.join(map(str, missing))}")
            partitions = {d: partitions[d] for d in dates}
        for departure_date, path in sorted(partitions.items()):
            rows = load_trains_partition(con, path, departure_date, force)
            if rows is None:
                summary.partitions_skipped += 1
            else:
                summary.partitions_loaded += 1
                summary.trains_loaded += rows
    finally:
        con.close()
    return summary
