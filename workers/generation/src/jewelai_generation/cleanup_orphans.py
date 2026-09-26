"""One-shot failed-generation orphan cleanup command; dry-run by default."""

import argparse
import json
import os

from jewelai_assets_gcs import GcsAssetStorageConfig, GcsPrivateObjectStore
from jewelai_persistence import (
    PersistenceRepository,
    create_database_engine,
    create_session_factory,
)

from .maintenance import (
    DEFAULT_MAINTENANCE_BATCH_SIZE,
    DEFAULT_ORPHAN_RETENTION_SECONDS,
    cleanup_failed_generation_orphans,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect or remove failed-generation orphan objects"
    )
    parser.add_argument(
        "--retention-seconds",
        type=int,
        default=int(
            os.getenv(
                "GENERATION_ORPHAN_RETENTION_SECONDS",
                str(DEFAULT_ORPHAN_RETENTION_SECONDS),
            )
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(
            os.getenv(
                "GENERATION_ORPHAN_CLEANUP_BATCH_SIZE",
                str(DEFAULT_MAINTENANCE_BATCH_SIZE),
            )
        ),
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    repository, storage = _runtime()
    summary = cleanup_failed_generation_orphans(
        repository,
        object_maintenance=storage,
        retention_seconds=args.retention_seconds,
        batch_size=args.batch_size,
        apply=args.apply,
    )
    print(json.dumps(summary.model_dump(), sort_keys=True))


def _runtime():
    database_url = os.getenv("DATABASE_URL")
    bucket = os.getenv("GCS_ASSET_BUCKET")
    if not database_url or not bucket:
        raise ValueError("DATABASE_URL and GCS_ASSET_BUCKET are required")
    repository = PersistenceRepository(create_session_factory(create_database_engine(database_url)))
    storage = GcsPrivateObjectStore(
        GcsAssetStorageConfig(bucket_name=bucket, project_id=os.getenv("GCP_PROJECT_ID"))
    )
    return repository, storage


if __name__ == "__main__":
    main()
