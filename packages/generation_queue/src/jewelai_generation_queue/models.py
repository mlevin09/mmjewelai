"""Strict provider-neutral generation dispatch contracts."""

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

GENERATION_TASK_SCHEMA_VERSION = "1.0.0"
MAX_DISPATCH_BATCH_SIZE = 100


class GenerationTaskContractError(ValueError):
    """The provider-neutral task contract is invalid."""


class GenerationTaskPublishError(RuntimeError):
    """Safe base error for task publication failures."""


class GenerationTaskPublishUnavailableError(GenerationTaskPublishError):
    """The configured delivery provider is temporarily unavailable."""


class GenerationTaskEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = GENERATION_TASK_SCHEMA_VERSION
    generation_run_id: UUID
    session_id: UUID
    organization_id: UUID


class PublishedGenerationTask(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str


class PendingGenerationDispatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task: GenerationTaskEnvelope
    created_at: datetime


class GenerationDispatchSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    inspected: int
    published: int
    failed: int


class GenerationTaskPublisher(Protocol):
    def publish(self, task: GenerationTaskEnvelope) -> PublishedGenerationTask: ...


class GenerationDispatchRepository(Protocol):
    def list_pending_generation_dispatches(
        self, batch_size: int
    ) -> tuple[PendingGenerationDispatch, ...]: ...

    def mark_generation_dispatch_published(
        self, generation_run_id: UUID, published_at: datetime
    ) -> datetime: ...


def generation_task_id(generation_run_id: UUID) -> str:
    """Return the one logical Cloud Tasks identity for a generation run."""
    return f"generation-{UUID(str(generation_run_id)).hex}"
