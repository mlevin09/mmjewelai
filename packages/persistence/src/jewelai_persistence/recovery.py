"""Bounded timeout-based recovery for abandoned generation executions."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict

from .repository import PersistenceRepository

DEFAULT_STALE_AFTER_SECONDS = 1800
MIN_STALE_AFTER_SECONDS = 900
MAX_STALE_AFTER_SECONDS = 86400
MAX_RECOVERY_BATCH_SIZE = 100


class StaleGenerationRecoverySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    inspected: int
    recovered: int
    skipped: int


def recover_stale_generation_runs(
    repository: PersistenceRepository,
    *,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
    batch_size: int = MAX_RECOVERY_BATCH_SIZE,
    clock: Callable[[], datetime] | None = None,
) -> StaleGenerationRecoverySummary:
    if isinstance(stale_after_seconds, bool) or not (
        MIN_STALE_AFTER_SECONDS <= stale_after_seconds <= MAX_STALE_AFTER_SECONDS
    ):
        raise ValueError("stale_after_seconds must be between 900 and 86400")
    if isinstance(batch_size, bool) or not 1 <= batch_size <= MAX_RECOVERY_BATCH_SIZE:
        raise ValueError("batch_size must be between 1 and 100")
    recovery_time = (clock or (lambda: datetime.now(UTC)))()
    cutoff = recovery_time - timedelta(seconds=stale_after_seconds)
    candidates = repository.list_stale_running_generation_runs(cutoff, batch_size)
    recovered = sum(
        repository.fail_stale_generation_run(
            candidate.generation_run_id,
            cutoff=cutoff,
            completed_at=recovery_time,
        )
        for candidate in candidates
    )
    return StaleGenerationRecoverySummary(
        inspected=len(candidates),
        recovered=recovered,
        skipped=len(candidates) - recovered,
    )
