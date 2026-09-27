"""One-shot bounded generation dispatch outbox redrive."""

import argparse
import json
import os
import sys

from jewelai_generation_queue import dispatch_pending_generation_tasks
from jewelai_generation_queue_gcp import CloudTasksGenerationPublisher
from jewelai_persistence import (
    PersistenceRepository,
    create_database_engine,
    create_session_factory,
)

from .settings import RuntimeSettings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    settings = RuntimeSettings.from_environment(require_oidc=False, require_asset_signer=False)
    if settings.generation_tasks is None:
        raise SystemExit("Cloud Tasks generation configuration is required")
    repository = PersistenceRepository(
        create_session_factory(create_database_engine(settings.database_url))
    )
    summary = dispatch_pending_generation_tasks(
        repository,
        CloudTasksGenerationPublisher(settings.generation_tasks),
        batch_size=args.batch_size,
    )
    print(
        json.dumps(
            {
                "severity": "INFO",
                "message": "outbox redrive finished",
                "service": "outbox-redrive",
                "environment": os.getenv("JEWELAI_ENVIRONMENT", "development"),
                "event": "outbox_redrive_finished",
                **summary.model_dump(),
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    print(summary.model_dump_json())


if __name__ == "__main__":
    main()
