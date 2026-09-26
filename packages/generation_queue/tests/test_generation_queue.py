import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from jewelai_generation_queue import (
    GENERATION_TASK_SCHEMA_VERSION,
    GenerationTaskEnvelope,
    GenerationTaskPublishUnavailableError,
    dispatch_pending_generation_tasks,
    generation_task_id,
    generation_task_json_schema,
)

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
SESSION_ID = UUID("22222222-2222-4222-8222-222222222222")
ORG_ID = UUID("33333333-3333-4333-8333-333333333333")


def task():
    return GenerationTaskEnvelope(
        generation_run_id=RUN_ID, session_id=SESSION_ID, organization_id=ORG_ID
    )


def test_envelope_is_strict_immutable_and_deterministic():
    value = task()
    assert value.schema_version == GENERATION_TASK_SCHEMA_VERSION
    assert value.model_dump_json() == task().model_dump_json()
    assert set(value.model_dump()) == {
        "schema_version",
        "generation_run_id",
        "session_id",
        "organization_id",
    }
    with pytest.raises(ValidationError):
        GenerationTaskEnvelope(**value.model_dump(), prompt="secret")
    with pytest.raises(ValidationError):
        value.session_id = RUN_ID


def test_task_id_is_deterministic():
    assert generation_task_id(RUN_ID) == "generation-11111111111141118111111111111111"


def test_payload_contains_no_secret_or_business_state():
    serialized = task().model_dump_json().lower()
    for forbidden in (
        "authorization",
        "bearer",
        "token",
        "email",
        "subject",
        "prompt",
        "provider",
        "model",
        "object_key",
        "signed_url",
        "base64",
        "bytes",
    ):
        assert forbidden not in serialized


def test_published_schema_has_no_drift():
    root = Path(__file__).resolve().parents[3]
    published = json.loads(
        (root / "specs/generation-queue/generation-task-v1.schema.json").read_text()
    )
    assert published == generation_task_json_schema()


class Repository:
    def __init__(self, dispatches):
        self.dispatches = dispatches
        self.marked = []

    def list_pending_generation_dispatches(self, batch_size):
        return tuple(self.dispatches[:batch_size])

    def mark_generation_dispatch_published(self, generation_run_id, published_at):
        self.marked.append((generation_run_id, published_at))
        return published_at


class Publisher:
    def __init__(self, fail=()):
        self.calls = []
        self.fail = set(fail)

    def publish(self, value):
        self.calls.append(value)
        if value.generation_run_id in self.fail:
            raise GenerationTaskPublishUnavailableError("unavailable")


def test_bounded_redrive_continues_after_typed_failure():
    from jewelai_generation_queue import PendingGenerationDispatch

    now = datetime(2026, 9, 26, tzinfo=UTC)
    second = task().model_copy(update={"generation_run_id": UUID(int=4)})
    repo = Repository(
        (
            PendingGenerationDispatch(task=task(), created_at=now),
            PendingGenerationDispatch(task=second, created_at=now),
        )
    )
    publisher = Publisher((RUN_ID,))
    summary = dispatch_pending_generation_tasks(repo, publisher, batch_size=2, clock=lambda: now)
    assert summary.model_dump() == {"inspected": 2, "published": 1, "failed": 1}
    assert repo.marked == [(second.generation_run_id, now)]
    with pytest.raises(ValueError):
        dispatch_pending_generation_tasks(repo, publisher, batch_size=101)
