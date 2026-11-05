"""Command-line entry point: train-elt {extract,load,transform,run,report,export,prune}."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

from train_elt import extract, load, report, transform
from train_elt.settings import Paths, completed_days, date_range, helsinki_today

log = logging.getLogger("train_elt")


def _add_date_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("dates (default: yesterday, Helsinki time)")
    group.add_argument("--date", type=date.fromisoformat, help="one departure date, YYYY-MM-DD")
    group.add_argument("--start", type=date.fromisoformat, help="first date of a range")
    group.add_argument("--end", type=date.fromisoformat, help="last date of a range")
    group.add_argument("--days", type=int, help="the last N complete days")


def _dates(args: argparse.Namespace) -> list[date]:
    if args.date and (args.start or args.end or args.days):
        raise SystemExit("--date cannot be combined with --start/--end/--days")
    if args.date:
        dates = [args.date]
    elif args.start:
        dates = date_range(args.start, args.end or helsinki_today() - timedelta(days=1))
    else:
        dates = completed_days(args.days or 1, end=args.end)
    if dates[-1] >= helsinki_today():
        raise SystemExit("only completed days can be extracted (today's trains are still running)")
    return dates


def cmd_extract(args: argparse.Namespace, paths: Paths) -> int:
    client = extract.DigitrafficClient()
    extract.extract_metadata(client, paths, force=args.force)
    results = [extract.extract_trains(client, paths, d, force=args.force) for d in _dates(args)]
    fetched = [r for r in results if not r.skipped]
    print(f"extract: {len(fetched)} day(s) fetched, {len(results) - len(fetched)} already landed")
    return 0


def cmd_load(args: argparse.Namespace, paths: Paths) -> int:
    summary = load.load_all(paths, force=args.force)
    print(
        f"load: {summary.partitions_loaded} partition(s) loaded "
        f"({summary.trains_loaded:,} trains), {summary.partitions_skipped} unchanged"
    )
    return 0


def cmd_transform(args: argparse.Namespace, paths: Paths) -> int:
    transform.build(paths, full_refresh=args.full_refresh)
    return 0


def cmd_run(args: argparse.Namespace, paths: Paths) -> int:
    cmd_extract(args, paths)
    cmd_load(args, paths)
    return cmd_transform(args, paths)


def cmd_report(args: argparse.Namespace, paths: Paths) -> int:
    text = report.markdown_report(paths, days=args.days, min_departures=args.min_departures)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


def cmd_export(args: argparse.Namespace, paths: Paths) -> int:
    for path in report.export_parquet(paths, args.output):
        print(path)
    return 0


def cmd_prune(args: argparse.Namespace, paths: Paths) -> int:
    """Delete landing partitions older than --keep-days (the warehouse keeps its rows)."""
    cutoff = helsinki_today() - timedelta(days=args.keep_days)
    removed = 0
    for departure_date, payload in load.landed_train_partitions(paths).items():
        if departure_date < cutoff:
            shutil.rmtree(payload.parent)
            removed += 1
    print(f"prune: removed {removed} landing partition(s) older than {cutoff}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="train-elt", description=__doc__)
    parser.add_argument("--data-dir", help="default: $TRAIN_ELT_DATA_DIR or ./data")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("extract", help="download trains and metadata into the landing zone")
    _add_date_args(p)
    p.add_argument("--force", action="store_true", help="re-download days already landed")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("load", help="load landing files into DuckDB raw tables")
    p.add_argument("--force", action="store_true", help="reload unchanged partitions")
    p.set_defaults(func=cmd_load)

    p = sub.add_parser("transform", help="dbt build (staging -> marts, with tests)")
    p.add_argument("--full-refresh", action="store_true", help="rebuild incremental models")
    p.set_defaults(func=cmd_transform)

    p = sub.add_parser("run", help="extract + load + transform")
    _add_date_args(p)
    p.add_argument("--force", action="store_true")
    p.add_argument("--full-refresh", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("report", help="print a Markdown punctuality summary")
    p.add_argument("--output", type=Path, help="write to a file instead of stdout")
    p.add_argument("--days", type=int, default=7, help="summarise the last N loaded days")
    p.add_argument("--min-departures", type=int, default=20)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("export", help="write the marts to Parquet")
    p.add_argument("--output", type=Path, help="default: <data-dir>/exports")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("prune", help="delete old landing partitions")
    p.add_argument("--keep-days", type=int, default=30)
    p.set_defaults(func=cmd_prune)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    paths = Paths.from_env(args.data_dir)
    try:
        return args.func(args, paths)
    except (extract.ExtractError, load.LoadError, transform.TransformError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
