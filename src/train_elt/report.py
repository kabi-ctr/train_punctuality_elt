"""Read the marts and produce a Markdown summary and Parquet exports."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import duckdb

from train_elt.settings import Paths

MARTS = [
    "dim_stations",
    "fct_train_runs",
    "fct_train_stops",
    "mart_daily_punctuality",
    "mart_station_daily",
    "mart_delay_causes",
]


def _table(headers: list[str], rows: list[tuple]) -> str:
    if not rows:
        return "_No rows._"

    def fmt(value) -> str:
        if value is None:
            return "–"
        if isinstance(value, float):
            return f"{value:,.1f}"
        if isinstance(value, int):
            return f"{value:,}"
        return str(value)

    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def markdown_report(
    paths: Paths, days: int = 7, min_departures: int = 20, min_trains: int = 10, top: int = 10
) -> str:
    """Summarise the last `days` loaded days."""
    con = duckdb.connect(str(paths.warehouse_path), read_only=True)
    try:
        (last,) = con.execute("SELECT max(departure_date) FROM marts.fct_train_runs").fetchone()
        if last is None:
            return "No train data loaded yet.\n"
        (first,) = con.execute(
            "SELECT min(departure_date) FROM marts.fct_train_runs WHERE departure_date >= ?",
            [last - timedelta(days=days - 1)],
        ).fetchone()
        period = [first, last]

        daily = con.execute(
            """
            SELECT departure_date, train_category, trains_scheduled, trains_cancelled,
                   trains_measured, trains_on_time, punctuality_pct, avg_arrival_delay_minutes
            FROM marts.mart_daily_punctuality
            WHERE service_group = 'All' AND departure_date BETWEEN ? AND ?
            ORDER BY departure_date, train_category
            """,
            period,
        ).fetchall()
        groups = con.execute(
            """
            SELECT train_category, service_group,
                   sum(trains_measured) AS measured,
                   round(100.0 * sum(trains_on_time) / nullif(sum(trains_measured), 0), 1) AS pct
            FROM marts.mart_daily_punctuality
            WHERE service_group <> 'All' AND departure_date BETWEEN ? AND ?
            GROUP BY ALL
            HAVING sum(trains_measured) >= ?
            ORDER BY pct, measured DESC
            LIMIT ?
            """,
            [*period, min_trains, top],
        ).fetchall()
        stations = con.execute(
            """
            SELECT station_name, station_code,
                   sum(departures_measured) AS departures,
                   round(sum(avg_departure_delay_minutes * departures_measured)
                         / nullif(sum(departures_measured), 0), 2) AS avg_delay,
                   round(100.0 * sum(departures_late) / nullif(sum(departures_measured), 0), 1)
                       AS pct_late
            FROM marts.mart_station_daily
            WHERE departure_date BETWEEN ? AND ?
            GROUP BY ALL
            HAVING sum(departures_measured) >= ?
            ORDER BY pct_late DESC, departures DESC
            LIMIT ?
            """,
            [*period, min_departures, top],
        ).fetchall()
        causes = con.execute(
            """
            SELECT coalesce(category_label_en, category_code), category_code,
                   sum(cause_reports), sum(trains_affected)
            FROM marts.mart_delay_causes
            WHERE departure_date BETWEEN ? AND ?
            GROUP BY ALL ORDER BY 3 DESC LIMIT ?
            """,
            [*period, top],
        ).fetchall()
    finally:
        con.close()

    title_period = str(first) if first == last else f"{first} – {last}"
    daily_headers = [
        "Date",
        "Category",
        "Trains",
        "Cancelled",
        "Measured",
        "On time",
        "Punctuality %",
        "Avg arrival delay (min)",
    ]
    parts = [
        f"## Finnish passenger train punctuality, {title_period}",
        "",
        "A train counts as on time if its final arrival is within the threshold for its "
        "category (long-distance 5 min, commuter 3 min by default).",
        "",
        "### Daily punctuality",
        "",
        _table(daily_headers, daily),
        "",
        f"### Least punctual services (≥ {min_trains} trains measured)",
        "",
        _table(["Category", "Line / train type", "Trains measured", "Punctuality %"], groups),
        "",
        f"### Stations with the most late departures (≥ {min_departures} departures)",
        "",
        _table(["Station", "Code", "Departures", "Avg delay (min)", "% late"], stations),
        "",
        "### Reported delay causes",
        "",
        _table(["Cause", "Code", "Reports", "Trains affected"], causes),
        "",
        "Source: Fintraffic / [digitraffic.fi](https://www.digitraffic.fi/), license "
        "[CC 4.0 BY](https://creativecommons.org/licenses/by/4.0/). "
        "Modified: aggregated into punctuality metrics.",
        "",
    ]
    return "\n".join(parts)


def export_parquet(paths: Paths, out_dir: Path | None = None) -> list[Path]:
    out_dir = out_dir or paths.exports_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(paths.warehouse_path), read_only=True)
    written = []
    try:
        for mart in MARTS:
            target = out_dir / f"{mart}.parquet"
            con.execute(
                f"COPY marts.{mart} TO '{target.as_posix()}' (FORMAT parquet, COMPRESSION zstd)"
            )
            written.append(target)
    finally:
        con.close()
    return written
