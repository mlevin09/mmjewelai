"""One-shot generated Asset reconciliation command."""

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
    DEFAULT_RECONCILIATION_GRACE_SECONDS,
    reconcile_generated_assets,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile durable generated Asset metadata")
    parser.add_argument(
        "--grace-seconds",
        type=int,
        default=int(
            os.getenv(
                "GENERATION_ASSET_RECONCILIATION_GRACE_SECONDS",
                str(DEFAULT_RECONCILIATION_GRACE_SECONDS),
            )
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(
            os.getenv(
                "GENERATION_ASSET_RECONCILIATION_BATCH_SIZE",
                str(DEFAULT_MAINTENANCE_BATCH_SIZE),
            )
        ),
    )
    args = parser.parse_args()
    repository, storage = _runtime()
    summary = reconcile_generated_assets(
        repository,
        object_reader=storage,
        grace_seconds=args.grace_seconds,
        batch_size=args.batch_size,
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
