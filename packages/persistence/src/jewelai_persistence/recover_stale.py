"""One-shot operator command for stale RUNNING generation recovery."""

import argparse
import os

from .database import create_database_engine, create_session_factory
from .recovery import (
    DEFAULT_STALE_AFTER_SECONDS,
    MAX_RECOVERY_BATCH_SIZE,
    recover_stale_generation_runs,
)
from .repository import PersistenceRepository


def _environment_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--batch-size",
        type=int,
        default=_environment_int("GENERATION_RECOVERY_BATCH_SIZE", MAX_RECOVERY_BATCH_SIZE),
    )
    parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=_environment_int("GENERATION_STALE_AFTER_SECONDS", DEFAULT_STALE_AFTER_SECONDS),
    )
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    repository = PersistenceRepository(create_session_factory(create_database_engine(database_url)))
    summary = recover_stale_generation_runs(
        repository,
        stale_after_seconds=args.stale_after_seconds,
        batch_size=args.batch_size,
    )
    print(summary.model_dump_json())


if __name__ == "__main__":
    main()
