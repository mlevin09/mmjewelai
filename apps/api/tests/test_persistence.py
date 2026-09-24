import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from jewelai_domain import Design, revise_design
from jewelai_domain.models import MessageSource
from jewelai_persistence import (
    Base,
    DuplicateRevisionError,
    OwnershipMismatchError,
    PersistenceRepository,
    StaleRevisionError,
    create_database_engine,
    create_session_factory,
)
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
        "message",
        "organization",
        "project",
        "question_event",
        "specification_revision",
    }
    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


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
