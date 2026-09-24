import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from jewelai_domain import Design, revise_design
from jewelai_domain.models import MessageSource
from jewelai_model_gateway import (
    GeneratedOutputDescriptor,
    GenerationConfiguration,
    GenerationErrorCode,
    GenerationResult,
    GenerationRun,
    GenerationStatus,
)
from jewelai_persistence import (
    Base,
    DuplicateRevisionError,
    GenerationStateConflictError,
    OwnershipMismatchError,
    PersistenceRepository,
    StaleRevisionError,
    create_database_engine,
    create_session_factory,
)
from jewelai_persistence.models import PromptRevisionRow
from jewelai_prompts import compile_prompt
from sqlalchemy import inspect

from jewelai_api.artifacts import load_runtime_artifacts
from jewelai_api.schemas import CreateSessionRequest
from jewelai_api.services import RuntimeService
from jewelai_api.settings import ArtifactVersions

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def build_service(engine):
    repository = PersistenceRepository(create_session_factory(engine))
    artifacts = load_runtime_artifacts(ROOT, ArtifactVersions())
    return RuntimeService(repository, artifacts, clock=lambda: NOW)


def create_persisted_session(service):
    organization = service.create_organization("Organization")
    project = service.create_project(organization.organization_id, "Project")
    session = service.create_session(
        project.project_id,
        organization.organization_id,
        CreateSessionRequest(role_id="retail_client", locale="en-US"),
    )
    return organization, project, session


def explicit(source, value):
    return {
        "availability": "value",
        "origin": "explicit",
        "value": value,
        "source": source.model_dump(mode="json"),
        "confirmed": False,
        "locked": False,
    }


def proposed_shape(current, shape):
    payload = current.design.model_dump(mode="json")
    payload["center_stone"]["shape"] = explicit(current.event.source, shape)
    return Design.model_validate(payload)


def next_revision(current, shape):
    return revise_design(
        current,
        proposed_shape(current, shape),
        expected_revision_id=current.revision_id,
        source=MessageSource(message_id=f"shape-{shape}", recorded_at=NOW),
        reason=f"Set shape to {shape}",
        created_at=NOW,
    )


def create_prompt_and_run(service, organization, session, prompt_id, run_id):
    current = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    compiled = compile_prompt(current, service.artifacts.prompts)
    service.repository.create_prompt_revision(
        PromptRevisionRow(
            prompt_revision_id=prompt_id,
            session_id=session.session_id,
            specification_revision_id=current.revision_id,
            prompt_schema_version=compiled.schema_version,
            compiler_version=compiled.compiler_version,
            template_id=compiled.template_id,
            template_version=compiled.template_version,
            template_artifact_version=compiled.template_artifact_version,
            compiled_text=compiled.prompt_text,
            structured_payload=compiled.model_dump(mode="json"),
            content_hash=compiled.content_hash,
            created_at=NOW,
        ),
        compiled,
        organization.organization_id,
        current.revision_id,
    )
    run = GenerationRun(
        generation_run_id=run_id,
        session_id=session.session_id,
        prompt_revision_id=prompt_id,
        prompt_content_hash=compiled.content_hash,
        profile_id="test_default",
        profile_version="1.0.0",
        provider="test",
        model="deterministic-image-v1",
        configuration=GenerationConfiguration(output_count=1),
        status=GenerationStatus.PENDING,
        created_at=NOW,
    )
    service.repository.create_generation_run(run, organization.organization_id)
    return compiled, run


def test_persistence_round_trip_lineage_pins_and_scope(engine):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    current = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    assert current.revision == 1
    assert current.design == Design()
    assert session.locale == "en"
    assert session.artifacts.model_dump() == {
        "design_schema": "1.0.0",
        "roles": "1.0.0",
        "dictionary": "1.0.0",
        "questions": "1.0.0",
        "rules": "1.0.0",
        "prompts": "1.0.0",
    }

    updated = next_revision(current, "oval")
    service.repository.append_revision_cas(
        session.session_id,
        organization.organization_id,
        current.revision_id,
        updated,
    )
    history = service.repository.list_revisions(session.session_id, organization.organization_id)
    assert history == (current, updated)
    assert history[1].parent_revision_id == history[0].revision_id
    assert history[0].design.center_stone.shape is None

    foreign = service.create_organization("Foreign")
    with pytest.raises(OwnershipMismatchError):
        service.repository.get_project(session.project_id, foreign.organization_id)
    with pytest.raises(OwnershipMismatchError):
        service.repository.get_design_session(session.session_id, foreign.organization_id)


def test_message_persistence_is_session_and_organization_scoped(engine):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    message = service.create_message(
        session.session_id, organization.organization_id, "A persisted user message"
    )
    stored = service.repository.get_message(
        session.session_id, message.message_id, organization.organization_id
    )
    assert stored.actor == "user"
    assert stored.content == "A persisted user message"
    assert stored.message_id == message.message_id
    assert stored.session_id == session.session_id
    assert stored.created_at.replace(tzinfo=UTC) == NOW

    foreign, _, foreign_session = create_persisted_session(service)
    with pytest.raises(OwnershipMismatchError):
        service.repository.get_message(
            session.session_id, message.message_id, foreign.organization_id
        )
    with pytest.raises(OwnershipMismatchError):
        service.repository.get_message(
            foreign_session.session_id, message.message_id, foreign.organization_id
        )


def test_compare_and_swap_rejects_second_writer_and_preserves_history(engine):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    current = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    first = next_revision(current, "oval")
    second = next_revision(current, "round")
    service.repository.append_revision_cas(
        session.session_id, organization.organization_id, current.revision_id, first
    )
    with pytest.raises(StaleRevisionError):
        service.repository.append_revision_cas(
            session.session_id, organization.organization_id, current.revision_id, second
        )
    assert service.repository.list_revisions(session.session_id, organization.organization_id) == (
        current,
        first,
    )


def test_repository_rejects_nonsequential_revision(engine):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    current = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    invalid = next_revision(current, "oval").model_copy(update={"revision": 3})
    with pytest.raises(DuplicateRevisionError, match="sequence"):
        service.repository.append_revision_cas(
            session.session_id,
            organization.organization_id,
            current.revision_id,
            invalid,
        )
    assert (
        service.repository.get_design_session(
            session.session_id, organization.organization_id
        ).current_revision_id
        == current.revision_id
    )


def test_alembic_upgrade_and_downgrade_from_empty_database(tmp_path, monkeypatch):
    database = tmp_path / "migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database}")
    config = Config(str(ROOT / "packages" / "persistence" / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_database_engine(f"sqlite+pysqlite:///{database}")
    assert set(inspect(engine).get_table_names()) == {
        "alembic_version",
        "design_session",
        "generation_run",
        "message",
        "organization",
        "project",
        "prompt_revision",
        "question_event",
        "specification_revision",
    }
    assert "prompt_artifact_version" in {
        column["name"] for column in inspect(engine).get_columns("design_session")
    }
    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_prompt_revision_round_trip_immutability_and_scope(engine):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    current = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    compiled = compile_prompt(current, service.artifacts.prompts)

    def row(identifier):
        return PromptRevisionRow(
            prompt_revision_id=identifier,
            session_id=session.session_id,
            specification_revision_id=current.revision_id,
            prompt_schema_version=compiled.schema_version,
            compiler_version=compiled.compiler_version,
            template_id=compiled.template_id,
            template_version=compiled.template_version,
            template_artifact_version=compiled.template_artifact_version,
            compiled_text=compiled.prompt_text,
            structured_payload=compiled.model_dump(mode="json"),
            content_hash=compiled.content_hash,
            created_at=NOW,
        )

    first_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    second_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    service.repository.create_prompt_revision(
        row(first_id), compiled, organization.organization_id, current.revision_id
    )
    service.repository.create_prompt_revision(
        row(second_id), compiled, organization.organization_id, current.revision_id
    )
    stored, restored = service.repository.get_prompt_revision(
        session.session_id, first_id, organization.organization_id
    )
    assert restored == compiled
    assert stored.compiled_text == compiled.prompt_text
    assert stored.content_hash == compiled.content_hash
    assert [
        item[0].prompt_revision_id
        for item in service.repository.list_prompt_revisions(
            session.session_id, organization.organization_id
        )
    ] == [first_id, second_id]

    foreign = service.create_organization("Foreign prompt owner")
    with pytest.raises(OwnershipMismatchError):
        service.repository.get_prompt_revision(
            session.session_id, first_id, foreign.organization_id
        )

    foreign_organization, _, foreign_session = create_persisted_session(service)
    foreign_current = service.repository.get_current_revision(
        foreign_session.session_id, foreign_organization.organization_id
    )
    foreign_compiled = compile_prompt(foreign_current, service.artifacts.prompts)
    mismatched = PromptRevisionRow(
        prompt_revision_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        session_id=session.session_id,
        specification_revision_id=foreign_current.revision_id,
        prompt_schema_version=foreign_compiled.schema_version,
        compiler_version=foreign_compiled.compiler_version,
        template_id=foreign_compiled.template_id,
        template_version=foreign_compiled.template_version,
        template_artifact_version=foreign_compiled.template_artifact_version,
        compiled_text=foreign_compiled.prompt_text,
        structured_payload=foreign_compiled.model_dump(mode="json"),
        content_hash=foreign_compiled.content_hash,
        created_at=NOW,
    )
    with pytest.raises(OwnershipMismatchError, match="does not belong"):
        service.repository.create_prompt_revision(
            mismatched,
            foreign_compiled,
            organization.organization_id,
            current.revision_id,
        )


def test_generation_run_lifecycle_round_trip_scope_and_terminal_immutability(engine):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    prompt_id = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    run_id = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
    compiled, pending = create_prompt_and_run(service, organization, session, prompt_id, run_id)
    assert (
        service.repository.get_generation_run(
            session.session_id, run_id, organization.organization_id
        )
        == pending
    )
    assert service.repository.list_generation_runs(
        session.session_id, organization.organization_id
    ) == (pending,)

    with pytest.raises(GenerationStateConflictError):
        service.repository.complete_generation_run(
            session.session_id,
            run_id,
            organization.organization_id,
            GenerationResult(
                generation_run_id=run_id,
                provider="test",
                model="deterministic-image-v1",
                outputs=(GeneratedOutputDescriptor(ordinal=1),),
            ),
            NOW,
        )
    running = service.repository.claim_generation_run(
        session.session_id, run_id, organization.organization_id, NOW
    )
    assert running.status is GenerationStatus.RUNNING
    result = GenerationResult(
        generation_run_id=run_id,
        provider="test",
        model="deterministic-image-v1",
        provider_request_id="provider-request",
        outputs=(GeneratedOutputDescriptor(ordinal=1, provider_output_id="provider-output"),),
    )
    succeeded = service.repository.complete_generation_run(
        session.session_id, run_id, organization.organization_id, result, NOW
    )
    assert succeeded.status is GenerationStatus.SUCCEEDED
    assert succeeded.result == result
    assert succeeded.prompt_revision_id == prompt_id
    assert succeeded.prompt_content_hash == compiled.content_hash
    assert succeeded.provider == "test"
    with pytest.raises(GenerationStateConflictError):
        service.repository.claim_generation_run(
            session.session_id, run_id, organization.organization_id, NOW
        )
    with pytest.raises(GenerationStateConflictError):
        service.repository.fail_generation_run(
            session.session_id,
            run_id,
            organization.organization_id,
            GenerationErrorCode.GATEWAY_UNAVAILABLE,
            "Cannot rewrite terminal run",
            NOW,
        )

    failed_id = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
    _, failed_pending = create_prompt_and_run(
        service,
        organization,
        session,
        UUID("abababab-abab-4bab-8bab-abababababab"),
        failed_id,
    )
    service.repository.claim_generation_run(
        session.session_id, failed_id, organization.organization_id, NOW
    )
    failed = service.repository.fail_generation_run(
        session.session_id,
        failed_id,
        organization.organization_id,
        GenerationErrorCode.PROVIDER_REJECTED,
        "Provider rejected the request",
        NOW,
    )
    assert failed.status is GenerationStatus.FAILED
    assert failed.result is None
    assert failed.error_code is GenerationErrorCode.PROVIDER_REJECTED
    assert failed.prompt_revision_id == failed_pending.prompt_revision_id
    with pytest.raises(GenerationStateConflictError):
        service.repository.claim_generation_run(
            session.session_id, failed_id, organization.organization_id, NOW
        )
    assert tuple(
        item.generation_run_id
        for item in service.repository.list_generation_runs(
            session.session_id, organization.organization_id
        )
    ) == (run_id, failed_id)

    foreign = service.create_organization("Foreign generation owner")
    with pytest.raises(OwnershipMismatchError):
        service.repository.get_generation_run(session.session_id, run_id, foreign.organization_id)


def test_generation_run_requires_prompt_from_same_session(engine):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    foreign_organization, _, foreign_session = create_persisted_session(service)
    prompt_id = UUID("12121212-1212-4212-8212-121212121212")
    foreign_run_id = UUID("13131313-1313-4313-8313-131313131313")
    compiled, _ = create_prompt_and_run(
        service, foreign_organization, foreign_session, prompt_id, foreign_run_id
    )
    mismatched = GenerationRun(
        generation_run_id=UUID("14141414-1414-4414-8414-141414141414"),
        session_id=session.session_id,
        prompt_revision_id=prompt_id,
        prompt_content_hash=compiled.content_hash,
        profile_id="test_default",
        profile_version="1.0.0",
        provider="test",
        model="deterministic-image-v1",
        configuration=GenerationConfiguration(),
        status=GenerationStatus.PENDING,
        created_at=NOW,
    )
    with pytest.raises(OwnershipMismatchError, match="does not belong"):
        service.repository.create_generation_run(mismatched, organization.organization_id)


@pytest.mark.postgres
def test_postgres_concurrent_compare_and_swap_allows_exactly_one_writer():
    database_url = os.getenv("TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("TEST_POSTGRES_URL is required for PostgreSQL concurrency coverage")
    engine = create_database_engine(database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    current = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    revisions = (next_revision(current, "oval"), next_revision(current, "round"))

    def persist(revision):
        repository = PersistenceRepository(create_session_factory(engine))
        try:
            repository.append_revision_cas(
                session.session_id,
                organization.organization_id,
                current.revision_id,
                revision,
            )
            return "success"
        except StaleRevisionError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(persist, revisions))
    assert sorted(outcomes) == ["stale", "success"]
    assert (
        len(service.repository.list_revisions(session.session_id, organization.organization_id))
        == 2
    )
    engine.dispose()


@pytest.mark.postgres
def test_postgres_concurrent_generation_claim_allows_exactly_one_worker():
    database_url = os.getenv("TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("TEST_POSTGRES_URL is required for PostgreSQL concurrency coverage")
    engine = create_database_engine(database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    run_id = UUID("15151515-1515-4515-8515-151515151515")
    create_prompt_and_run(
        service,
        organization,
        session,
        UUID("16161616-1616-4616-8616-161616161616"),
        run_id,
    )

    def claim():
        repository = PersistenceRepository(create_session_factory(engine))
        try:
            repository.claim_generation_run(
                session.session_id, run_id, organization.organization_id, NOW
            )
            return "claimed"
        except GenerationStateConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(lambda _: claim(), range(2)))
    assert sorted(outcomes) == ["claimed", "conflict"]
    assert (
        service.repository.get_generation_run(
            session.session_id, run_id, organization.organization_id
        ).status
        is GenerationStatus.RUNNING
    )
    engine.dispose()
