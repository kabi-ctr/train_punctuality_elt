"""Transform: run the dbt project in transform/ against the DuckDB warehouse.

dbt runs in a child process. dbt-duckdb keeps its database handle open for the
life of the process, so running it in-process would lock the warehouse file
for every later step (report, export, the next load).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys

from train_elt.settings import DBT_PROJECT_DIR, Paths

log = logging.getLogger(__name__)

DBT_ENTRYPOINT = "from dbt.cli.main import cli; cli()"


class TransformError(RuntimeError):
    pass


def run_dbt(paths: Paths, command: list[str], dbt_vars: dict | None = None) -> None:
    """Run one dbt command, e.g. ["build"] or ["build", "--full-refresh"]."""
    if not paths.warehouse_path.exists():
        raise TransformError(f"{paths.warehouse_path} does not exist; run load first")
    args = [
        sys.executable,
        "-c",
        DBT_ENTRYPOINT,
        *command,
        "--project-dir",
        str(DBT_PROJECT_DIR),
        "--profiles-dir",
        str(DBT_PROJECT_DIR),
    ]
    if dbt_vars:
        args += ["--vars", json.dumps(dbt_vars)]
    env = {**os.environ, "TRAIN_ELT_DUCKDB_PATH": str(paths.warehouse_path.resolve())}
    log.info("dbt %s", " ".join(command))
    completed = subprocess.run(args, env=env, cwd=DBT_PROJECT_DIR, check=False)
    if completed.returncode != 0:
        raise TransformError(f"dbt {' '.join(command)} failed (exit code {completed.returncode})")


def build(paths: Paths, full_refresh: bool = False, dbt_vars: dict | None = None) -> None:
    run_dbt(paths, ["build", *(["--full-refresh"] if full_refresh else [])], dbt_vars)
