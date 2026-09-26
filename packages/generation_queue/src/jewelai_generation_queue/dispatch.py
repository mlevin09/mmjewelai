"""Bounded, provider-neutral transactional-outbox redrive."""

from collections.abc import Callable
from datetime import UTC, datetime

from .models import (
    MAX_DISPATCH_BATCH_SIZE,
    GenerationDispatchRepository,
    GenerationDispatchSummary,
    GenerationTaskPublisher,
    GenerationTaskPublishError,
)


def dispatch_pending_generation_tasks(
    repository: GenerationDispatchRepository,
    publisher: GenerationTaskPublisher,
    *,
    batch_size: int = 100,
    clock: Callable[[], datetime] | None = None,
) -> GenerationDispatchSummary:
    if isinstance(batch_size, bool) or not 1 <= batch_size <= MAX_DISPATCH_BATCH_SIZE:
        raise ValueError("batch_size must be between 1 and 100")
    clock = clock or (lambda: datetime.now(UTC))
    pending = repository.list_pending_generation_dispatches(batch_size)
    published = 0
    failed = 0
    for dispatch in pending:
        try:
            publisher.publish(dispatch.task)
        except GenerationTaskPublishError:
            failed += 1
            continue
        repository.mark_generation_dispatch_published(dispatch.task.generation_run_id, clock())
        published += 1
    return GenerationDispatchSummary(inspected=len(pending), published=published, failed=failed)
