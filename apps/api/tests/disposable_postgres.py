"""Independently identify the fresh CI Postgres service BEFORE any B2 test DDL.

An environment variable or a test-looking database name alone is not permission to mutate it.
No arbitrary local/preproduction/production connection is accepted by this helper.
"""

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta

from jewelai_persistence import create_database_engine
from sqlalchemy import text

CI_URL = "postgresql+psycopg://jewelai:jewelai@localhost:5432/jewelai_test"


def _docker(*args):
    return subprocess.check_output(["docker", *args], text=True, timeout=15).strip()


def verified_ci_postgres():
    """Compare the real disposable container's cluster identity to the SQL connection."""
    if (
        os.getenv("GITHUB_ACTIONS") != "true"
        or os.getenv("GITHUB_REPOSITORY") != "mlevin09/mmjewelai"
        or os.getenv("GITHUB_JOB") != "runtime"
        or os.getenv("TEST_POSTGRES_URL") != CI_URL
    ):
        raise RuntimeError("B2 PostgreSQL target is not independently verified disposable storage")
    candidates = []
    for container_id in _docker(
        "ps", "--filter", "ancestor=postgres:16", "--format", "{{.ID}}"
    ).splitlines():
        metadata = json.loads(_docker("inspect", container_id))[0]
        ports = metadata["NetworkSettings"]["Ports"].get("5432/tcp") or []
        if any(port["HostPort"] == "5432" for port in ports):
            candidates.append((container_id, metadata))
    if len(candidates) != 1:
        raise RuntimeError("B2 did not identify exactly one disposable CI PostgreSQL service")
    container_id, metadata = candidates[0]
    started = datetime.fromisoformat(metadata["State"]["StartedAt"].replace("Z", "+00:00"))
    if (
        metadata["Config"]["Image"] != "postgres:16"
        or not metadata["State"]["Running"]
        or not timedelta(0) <= datetime.now(UTC) - started < timedelta(hours=2)
    ):
        raise RuntimeError("B2 PostgreSQL service is not a fresh disposable container")
    cluster_id = _docker(
        "exec",
        container_id,
        "psql",
        "-U",
        "jewelai",
        "-d",
        "jewelai_test",
        "-Atc",
        "SELECT system_identifier FROM pg_control_system()",
    )
    engine = create_database_engine(CI_URL)
    try:
        with engine.connect() as db:
            actual = str(db.scalar(text("SELECT system_identifier FROM pg_control_system()")))
            version = int(db.scalar(text("SHOW server_version_num")))
        if actual != cluster_id or not 160000 <= version < 170000:
            raise RuntimeError("B2 SQL target does not match the disposable PostgreSQL container")
    finally:
        engine.dispose()
    return CI_URL
