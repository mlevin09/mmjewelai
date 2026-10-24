import copy
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

import pytest
from jewelai_domain import (
    REQUIRED_PRODUCTION_VALIDATION_CHECKS,
    ProductionValidationCheck,
    ProductionValidationReport,
    RuntimeProvenance,
    RuntimeSemanticState,
    compile_knowledge_library,
    load_parametric_knowledge,
    promote_knowledge_runtime,
)
from jewelai_domain.knowledge_storage import (
    KnowledgeArtifactStorageError,
    KnowledgeArtifactStore,
)
from jewelai_persistence import (
    Base,
    EnrichmentCycleConflictError,
    EnrichmentIntegrityError,
    KnowledgeReleasePinConflictError,
    NotFoundError,
    PersistenceRepository,
    StaleRevisionError,
    create_database_engine,
    create_session_factory,
)
from jewelai_persistence.models import EnrichmentCycleRow
from jewelai_prompts import (
    EnrichmentProposal,
    enrich_prompt,
    enrich_prompt_with_active_release,
    load_prompt_templates,
)
from sqlalchemy import select
from test_persistence import NOW, build_service, create_persisted_session, next_revision

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "data" / "knowledge" / "v1" / "three-stone-1.0.0.json"
PROMPTS = ROOT / "data" / "prompts" / "v1.0.0.json"
PARAMETRIC = ROOT / "data" / "knowledge-base" / "v1.0.0.json"


def _bundle(*, version="1.0.0", suffix=""):
    payload = json.loads(PACKAGE.read_text(encoding="utf-8"))
    payload["artifact_version"] = version
    if suffix:
        payload["sources"][0]["title"] += suffix
    return payload


def _report(runtime):
    return ProductionValidationReport(
        package_id=runtime.package_id,
        artifact_version=runtime.artifact_version,
        runtime_sha256=runtime.sha256,
        checks=tuple(
            ProductionValidationCheck(
                name=name,
                outcome="PASS",
                evidence_ref=f"ci://{name}",
            )
            for name in REQUIRED_PRODUCTION_VALIDATION_CHECKS
        ),
    )


def _verified_result(store, revision, *, version="1.0.0", suffix=""):
    payload = _bundle(version=version, suffix=suffix)
    stored = store.publish(payload)
    runtime, _ = compile_knowledge_library(payload)
    report = _report(runtime)
    active = promote_knowledge_runtime(runtime, report)
    parametric = load_parametric_knowledge(PARAMETRIC)
    result = enrich_prompt_with_active_release(
        revision,
        load_prompt_templates(PROMPTS),
        store,
        knowledge_package_id=stored.package_id,
        knowledge_artifact_version=stored.artifact_version,
        active_release=active,
        validation_report=report,
        parametric_catalog_id=parametric.catalog_id,
        parametric_artifact_version=str(parametric.artifact_version),
        parametric_catalog_sha256=parametric.sha256,
        proposals=(
            EnrichmentProposal(
                target="center_stone.setting",
                semantic_state=RuntimeSemanticState.RECOMMENDED,
                provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
                value="prong_setting",
                source_id="DEC-THREE-STONE-POLICY",
            ),
        ),
    )
    return stored, report, active, result


def _persist(repository, organization_id, session_id, revision_id, result, *, number, cycle_id):
    return repository.create_enrichment_cycle(
        enrichment_cycle_id=cycle_id,
        session_id=session_id,
        organization_id=organization_id,
        expected_revision_id=revision_id,
        expected_previous_cycle_number=number - 1,
        result=result,
        created_at=NOW,
    )


def test_release_pin_and_enrichment_history_survive_repository_restart(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    revision = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    revision_before = copy.deepcopy(revision)
    store = KnowledgeArtifactStore(tmp_path / "knowledge")
    stored, report, active, result = _verified_result(store, revision)

    first_id = UUID("10101010-1010-4010-8010-101010101010")
    first = _persist(
        service.repository,
        organization.organization_id,
        session.session_id,
        revision.revision_id,
        result,
        number=1,
        cycle_id=first_id,
    )

    restarted = PersistenceRepository(create_session_factory(engine))
    pin = restarted.get_knowledge_release_pin(session.session_id, organization.organization_id)
    restored_runtime = restarted.restore_pinned_knowledge_runtime(
        session.session_id,
        organization.organization_id,
        store,
        active_release=active,
        validation_report=report,
    )
    restored_first = restarted.get_enrichment_cycle(
        session.session_id, first_id, organization.organization_id
    )

    assert first == restored_first
    assert pin.package_id == stored.package_id
    assert pin.artifact_version == stored.artifact_version
    assert pin.runtime_sha256 == active.runtime_sha256
    assert pin.validation_report_sha256 == report.sha256
    assert restored_runtime.runtime_sha256 == pin.runtime_sha256
    assert restored_first.result == result
    assert restored_first.result.decisions[0].proposal.source_id == "DEC-THREE-STONE-POLICY"
    assert restored_first.result.final_matrix
    assert (
        service.repository.get_current_revision(session.session_id, organization.organization_id)
        == revision_before
    )
    assert revision.design.center_stone.setting is None

    second_id = UUID("20202020-2020-4020-8020-202020202020")
    _persist(
        restarted,
        organization.organization_id,
        session.session_id,
        revision.revision_id,
        result,
        number=2,
        cycle_id=second_id,
    )
    history = restarted.list_enrichment_cycles(session.session_id, organization.organization_id)
    assert [item.enrichment_cycle_id for item in history] == [first_id, second_id]
    assert [item.cycle_number for item in history] == [1, 2]
    assert history[0] == restored_first


def test_pin_never_falls_forward_and_conflicting_release_is_rejected(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    revision = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    store = KnowledgeArtifactStore(tmp_path / "knowledge")
    _, first_report, first_active, first_result = _verified_result(store, revision)
    _persist(
        service.repository,
        organization.organization_id,
        session.session_id,
        revision.revision_id,
        first_result,
        number=1,
        cycle_id=UUID("30303030-3030-4030-8030-303030303030"),
    )

    _, second_report, second_active, second_result = _verified_result(
        store, revision, version="1.1.0", suffix=" v1.1"
    )
    restored = service.repository.restore_pinned_knowledge_runtime(
        session.session_id,
        organization.organization_id,
        store,
        active_release=first_active,
        validation_report=first_report,
    )
    assert str(restored.artifact_version) == "1.0.0"

    with pytest.raises(KnowledgeReleasePinConflictError, match="different Knowledge release"):
        _persist(
            service.repository,
            organization.organization_id,
            session.session_id,
            revision.revision_id,
            second_result,
            number=2,
            cycle_id=UUID("40404040-4040-4040-8040-404040404040"),
        )
    with pytest.raises(KnowledgeArtifactStorageError, match="explicitly selected release"):
        service.repository.restore_pinned_knowledge_runtime(
            session.session_id,
            organization.organization_id,
            store,
            active_release=second_active,
            validation_report=second_report,
        )


def test_stale_duplicate_and_conflicting_cycle_writes_fail_atomically(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    original = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    store = KnowledgeArtifactStore(tmp_path / "knowledge")
    _, _, _, result = _verified_result(store, original)
    cycle_id = UUID("50505050-5050-4050-8050-505050505050")
    _persist(
        service.repository,
        organization.organization_id,
        session.session_id,
        original.revision_id,
        result,
        number=1,
        cycle_id=cycle_id,
    )

    with pytest.raises(EnrichmentCycleConflictError, match="sequence changed"):
        _persist(
            service.repository,
            organization.organization_id,
            session.session_id,
            original.revision_id,
            result,
            number=1,
            cycle_id=UUID("60606060-6060-4060-8060-606060606060"),
        )
    with pytest.raises(EnrichmentCycleConflictError, match="already exists"):
        _persist(
            service.repository,
            organization.organization_id,
            session.session_id,
            original.revision_id,
            result,
            number=2,
            cycle_id=cycle_id,
        )

    advanced = next_revision(original, "round")
    service.repository.append_revision_cas(
        session.session_id,
        organization.organization_id,
        original.revision_id,
        advanced,
    )
    with pytest.raises(StaleRevisionError, match="changed during enrichment"):
        _persist(
            service.repository,
            organization.organization_id,
            session.session_id,
            original.revision_id,
            result,
            number=2,
            cycle_id=UUID("70707070-7070-4070-8070-707070707070"),
        )
    assert (
        len(
            service.repository.list_enrichment_cycles(
                session.session_id, organization.organization_id
            )
        )
        == 1
    )


def test_restore_fails_closed_for_tampered_artifact_or_result(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    revision = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    store = KnowledgeArtifactStore(tmp_path / "knowledge")
    stored, report, active, result = _verified_result(store, revision)
    cycle_id = UUID("80808080-8080-4080-8080-808080808080")
    _persist(
        service.repository,
        organization.organization_id,
        session.session_id,
        revision.revision_id,
        result,
        number=1,
        cycle_id=cycle_id,
    )

    runtime_path = (
        tmp_path / "knowledge" / stored.package_id / stored.artifact_version / "runtime.json"
    )
    runtime_path.write_text(runtime_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(KnowledgeArtifactStorageError, match="checksum mismatch"):
        service.repository.restore_pinned_knowledge_runtime(
            session.session_id,
            organization.organization_id,
            store,
            active_release=active,
            validation_report=report,
        )

    with create_session_factory(engine).begin() as db:
        row = db.scalar(
            select(EnrichmentCycleRow).where(EnrichmentCycleRow.enrichment_cycle_id == cycle_id)
        )
        payload = dict(row.result_payload)
        payload["content_hash"] = "0" * 64
        row.result_payload = payload
    with pytest.raises(EnrichmentIntegrityError, match="stored enrichment result is invalid"):
        service.repository.get_enrichment_cycle(
            session.session_id, cycle_id, organization.organization_id
        )


def test_unpinned_session_and_foreign_scope_fail_closed(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    foreign, _, _ = create_persisted_session(service)

    with pytest.raises(NotFoundError, match="no verified Knowledge release pin"):
        service.repository.get_knowledge_release_pin(
            session.session_id, organization.organization_id
        )
    with pytest.raises(NotFoundError):
        service.repository.list_enrichment_cycles(session.session_id, foreign.organization_id)

    revision = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    runtime, _ = compile_knowledge_library(_bundle())
    unverified = enrich_prompt(revision, load_prompt_templates(PROMPTS), runtime)
    with pytest.raises(EnrichmentIntegrityError, match="verified ACTIVE release provenance"):
        _persist(
            service.repository,
            organization.organization_id,
            session.session_id,
            revision.revision_id,
            unverified,
            number=1,
            cycle_id=UUID("85858585-8585-4585-8585-858585858585"),
        )
    with pytest.raises(NotFoundError, match="no verified Knowledge release pin"):
        service.repository.get_knowledge_release_pin(
            session.session_id, organization.organization_id
        )


@pytest.mark.postgres
def test_postgres_concurrent_enrichment_commit_allows_exactly_one_writer(tmp_path):
    database_url = os.getenv("TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("TEST_POSTGRES_URL is required for PostgreSQL concurrency coverage")
    engine = create_database_engine(database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    revision = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    _, _, _, result = _verified_result(KnowledgeArtifactStore(tmp_path / "knowledge"), revision)

    def commit(cycle_id):
        repository = PersistenceRepository(create_session_factory(engine))
        try:
            _persist(
                repository,
                organization.organization_id,
                session.session_id,
                revision.revision_id,
                result,
                number=1,
                cycle_id=cycle_id,
            )
            return "success"
        except EnrichmentCycleConflictError:
            return "conflict"

    identifiers = (
        UUID("90909090-9090-4090-8090-909090909090"),
        UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(commit, identifiers))
    assert sorted(outcomes) == ["conflict", "success"]
    assert (
        len(
            service.repository.list_enrichment_cycles(
                session.session_id, organization.organization_id
            )
        )
        == 1
    )
    engine.dispose()
