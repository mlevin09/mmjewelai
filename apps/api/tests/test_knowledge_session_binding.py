"""KRT release identity/rollback gates. All releases and identities are synthetic."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from jewelai_domain.knowledge_runtime import bind_verified_release, knowledge_store
from jewelai_domain.knowledge_storage import KnowledgeArtifactStore
from jewelai_persistence import EnrichmentIntegrityError
from jewelai_persistence.models import (
    DesignSessionRow,
    EnrichmentCycleRow,
    KnowledgeReleaseBindingRow,
)
from sqlalchemy import func, select, update
from test_enrichment_persistence import _persist, _verified_result
from test_persistence import NOW, build_service, create_persisted_session
from test_prompt_enrichment_runtime import _request, _runtime

from jewelai_api.prompt_enrichment_runtime import (
    PromptEnrichmentRuntimeError,
    PromptEnrichmentRuntimeService,
)


def state_counts(engine, session_id):
    with engine.connect() as db:
        return tuple(
            db.scalar(select(func.count()).select_from(model).where(model.session_id == session_id))
            for model in (EnrichmentCycleRow, KnowledgeReleaseBindingRow)
        )


def test_new_session_rejects_legacy_but_historical_pin_restores_without_rewriting(engine, tmp_path):
    service = build_service(engine)
    org, _, session = create_persisted_session(service)
    revision = service.repository.get_current_revision(session.session_id, org.organization_id)
    store = KnowledgeArtifactStore(tmp_path / "legacy")
    stored, report, active, result = _verified_result(store, revision)
    runtime = PromptEnrichmentRuntimeService(
        service.repository,
        service.artifacts,
        store,
        knowledge_package_id=stored.package_id,
        knowledge_artifact_version=stored.artifact_version,
        active_release=active,
        validation_report=report,
        clock=lambda: NOW,
        uuid_factory=uuid4,
    )
    request = _request(service, org, session, "Create an oval ring.")
    with pytest.raises(PromptEnrichmentRuntimeError, match="require Knowledge Contract 1.1.0"):
        runtime.start_initial_message(request)
    assert state_counts(engine, session.session_id) == (0, 0)
    # Low-level append represents retained historical data, not new controlled intake.
    _persist(
        service.repository,
        org.organization_id,
        session.session_id,
        revision.revision_id,
        result,
        number=1,
        cycle_id=uuid4(),
    )
    before = service.repository.list_enrichment_cycles(session.session_id, org.organization_id)[
        0
    ].result.model_dump_json()
    restored = service.repository.restore_pinned_knowledge_runtime(
        session.session_id,
        org.organization_id,
        store,
        active_release=active,
        validation_report=report,
    )
    assert restored == active and restored.contract_version == "1.0.0"
    assert (
        service.repository.list_enrichment_cycles(session.session_id, org.organization_id)[
            0
        ].result.model_dump_json()
        == before
    )
    with pytest.raises(RuntimeError, match="contract"):
        service.repository.restore_pinned_knowledge_runtime(
            session.session_id,
            org.organization_id,
            knowledge_store("1.1.0", store.root),
            active_release=active,
            validation_report=report,
        )


@pytest.mark.parametrize("failure", ["plan_write", "stale", "report"])
def test_failed_initial_operation_has_no_binding_pin_cycle_or_revision(
    engine, tmp_path, monkeypatch, failure
):
    service = build_service(engine)
    org, _, session = create_persisted_session(service)
    runtime, store, active, report = _runtime(service, tmp_path)
    request = _request(service, org, session, "Create a white-gold oval ring.")
    before = service.repository.get_current_revision(session.session_id, org.organization_id)
    if failure == "plan_write":

        def fail(*args, **kwargs):
            raise RuntimeError("Injected transactional plan failure")

        monkeypatch.setattr(service.repository, "_add_clarification_plan", fail)
    elif failure == "stale":
        request = request.model_copy(update={"expected_revision_id": uuid4()})
    else:
        runtime.validation_report = report.model_copy(update={"runtime_sha256": "0" * 64})
    with pytest.raises((ValueError, RuntimeError)):
        runtime.start_initial_message(request)
    assert state_counts(engine, session.session_id) == (0, 0)
    assert (
        service.repository.get_current_revision(session.session_id, org.organization_id) == before
    )
    with engine.connect() as db:
        assert (
            db.scalar(
                select(DesignSessionRow.knowledge_runtime_sha256).where(
                    DesignSessionRow.session_id == session.session_id
                )
            )
            is None
        )


@pytest.mark.parametrize("tamper", ["payload", "hash", "marker", "missing"])
def test_stored_binding_tamper_rejected_on_restore(engine, tmp_path, tamper):
    service = build_service(engine)
    org, _, session = create_persisted_session(service)
    runtime, *_ = _runtime(service, tmp_path)
    runtime.start_initial_message(_request(service, org, session, "Create an oval ring."))
    with engine.begin() as db:
        if tamper == "marker":
            db.execute(
                update(EnrichmentCycleRow)
                .where(EnrichmentCycleRow.session_id == session.session_id)
                .values(knowledge_contract_version="1.0.0")
            )
        elif tamper == "missing":
            db.execute(
                KnowledgeReleaseBindingRow.__table__.delete().where(
                    KnowledgeReleaseBindingRow.session_id == session.session_id
                )
            )
        elif tamper == "payload":
            payload = db.scalar(select(KnowledgeReleaseBindingRow.payload))
            payload["knowledge_contract_version"] = "1.0.0"
            db.execute(update(KnowledgeReleaseBindingRow).values(payload=payload))
        else:
            db.execute(update(KnowledgeReleaseBindingRow).values(content_hash="0" * 64))
    with pytest.raises(EnrichmentIntegrityError):
        service.repository.get_knowledge_release_pin(session.session_id, org.organization_id)


def test_duplicate_and_concurrent_initial_are_single_binding(engine, tmp_path):
    service = build_service(engine)
    org, _, session = create_persisted_session(service)
    runtime, store, active, report = _runtime(service, tmp_path)
    request = _request(service, org, session, "Create an oval ring.")

    def start():
        try:
            runtime.start_initial_message(request)
            return True
        except (ValueError, RuntimeError):
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: start(), range(2)))
    assert sum(outcomes) == 1
    assert not start()
    assert state_counts(engine, session.session_id) == (1, 1)
    pin = service.repository.get_knowledge_release_pin(session.session_id, org.organization_id)
    assert pin.binding == bind_verified_release(
        store,
        active.package_id,
        active.artifact_version,
        active_release=active,
        validation_report=report,
    )


def test_in_memory_session_correction_keeps_outer_transaction(tmp_path, monkeypatch):
    from jewelai_persistence import Base
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from test_prompt_enrichment_composition import (
        test_enabled_composition_qualifies_release_and_runs_restart_safe_full_http_cycle as cycle,
    )

    memory = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(memory)
    try:
        cycle(
            memory,
            tmp_path,
            monkeypatch,
            "en-US",
            "A white or yellow-gold three-stone ring with an oval sapphire and no halo.",
        )
    finally:
        memory.dispose()
