import os
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from jewelai_domain.models import MessageSource
from jewelai_domain.questions import QuestionId
from jewelai_persistence import (
    Base,
    ClarificationDecisionConflictError,
    ClarificationDecisionIntegrityError,
    KnowledgeReleasePinConflictError,
    OwnershipMismatchError,
    PersistenceRepository,
    StaleRevisionError,
    UserCorrectionConflictError,
    UserCorrectionIntegrityError,
    create_database_engine,
    create_session_factory,
)
from sqlalchemy import event, update
from test_enrichment_persistence import _verified_result
from test_persistence import NOW, build_service, create_persisted_session, next_revision

from jewelai_api.clarification import ClarificationOption
from jewelai_api.clarification_answers import (
    ClarificationAnswerOutcome,
    ClarificationAnswerReason,
    ClarificationAnswerResult,
    ClarificationDecision,
)
from jewelai_api.clarification_answers import _hash as answer_hash
from jewelai_api.clarification_answers import _json as answer_json
from jewelai_api.correction_enrichment import UserCorrection, process_user_correction
from jewelai_api.durable_enrichment import (
    commit_clarification_answer_result,
    commit_user_correction_result,
    get_clarification_answer_result,
    get_user_correction_result,
)

ANSWER_ID = UUID("11111111-1111-4111-8111-111111111111")
CYCLE_ID = UUID("22222222-2222-4222-8222-222222222222")
NEXT_CYCLE_ID = UUID("33333333-3333-4333-8333-333333333333")
CORRECTION_ID = UUID("44444444-4444-4444-8444-444444444444")


def _setup(service, tmp_path):
    organization, _, session = create_persisted_session(service)
    revision = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    from jewelai_domain.knowledge_storage import KnowledgeArtifactStore

    store = KnowledgeArtifactStore(tmp_path / str(session.session_id))
    stored, report, active, enrichment = _verified_result(store, revision)
    cycle = service.repository.create_enrichment_cycle(
        enrichment_cycle_id=CYCLE_ID,
        session_id=session.session_id,
        organization_id=organization.organization_id,
        expected_revision_id=revision.revision_id,
        expected_previous_cycle_number=0,
        result=enrichment,
        created_at=NOW,
    )
    return organization, session, revision, store, stored, report, active, cycle


def _answer_result(session_id, revision, cycle, *, decision, outcome, reason, changed=False):
    resulting = next_revision(revision, "round") if changed else None
    payload = {
        "answer_version": "1.0.0",
        "session_id": session_id,
        "plan_content_hash": "a" * 64,
        "clarification_id": "clarification-center-shape",
        "semantic_question_id": QuestionId.CENTER_STONE_SHAPE,
        "decision": decision,
        "selected_option": (
            ClarificationOption(value="round", label="Round", source_ids=("candidate-1",))
            if decision == ClarificationDecision.SELECT_OPTION
            else None
        ),
        "source_candidate_ids": ("candidate-1",),
        "source_proposal_ids": ("proposal-1",),
        "evidence": (),
        "target": "center_stone.shape",
        "subject": None,
        "previous_revision_id": revision.revision_id,
        "new_revision_id": resulting.revision_id if resulting else None,
        "resulting_revision": resulting,
        "knowledge_package_id": cycle.release_pin.package_id,
        "knowledge_artifact_version": cycle.release_pin.artifact_version,
        "knowledge_runtime_sha256": cycle.release_pin.runtime_sha256,
        "knowledge_validation_report_sha256": cycle.release_pin.validation_report_sha256,
        "question_artifact_version": "1.0.0",
        "rules_artifact_version": "1.0.0",
        "outcome": outcome,
        "reason": reason,
        "question_resolved": outcome not in {ClarificationAnswerOutcome.UNKNOWN},
        "blocks_progression": outcome == ClarificationAnswerOutcome.UNKNOWN,
        "answer_hash": answer_hash({"decision": decision.value, "session_id": str(session_id)}),
    }
    return ClarificationAnswerResult(
        **payload,
        content_hash=answer_hash(answer_json(payload)),
    )


def _changed_answer(result, **changes):
    payload = result.model_dump(mode="json", exclude={"content_hash"})
    payload.update(changes)
    return ClarificationAnswerResult(
        **payload,
        content_hash=answer_hash(payload),
    )


@pytest.mark.parametrize(
    ("decision", "outcome", "reason"),
    [
        (
            ClarificationDecision.ACCEPT,
            ClarificationAnswerOutcome.NO_CHANGE,
            ClarificationAnswerReason.VALUE_ALREADY_CURRENT,
        ),
        (
            ClarificationDecision.REJECT,
            ClarificationAnswerOutcome.REJECTED,
            ClarificationAnswerReason.USER_REJECTED_OFFER,
        ),
        (
            ClarificationDecision.SKIP,
            ClarificationAnswerOutcome.SKIPPED,
            ClarificationAnswerReason.USER_SKIPPED,
        ),
        (
            ClarificationDecision.UNKNOWN,
            ClarificationAnswerOutcome.UNKNOWN,
            ClarificationAnswerReason.USER_DOES_NOT_KNOW,
        ),
        (
            ClarificationDecision.SELECT_OPTION,
            ClarificationAnswerOutcome.APPLIED,
            ClarificationAnswerReason.USER_SELECTED_OFFERED_OPTION,
        ),
    ],
)
def test_nonmutating_clarification_decisions_are_durable(
    engine, tmp_path, decision, outcome, reason
):
    service = build_service(engine)
    organization, session, revision, *_, cycle = _setup(service, tmp_path)
    result = _answer_result(
        session.session_id,
        revision,
        cycle,
        decision=decision,
        outcome=outcome,
        reason=reason,
        changed=decision == ClarificationDecision.SELECT_OPTION,
    )

    committed = commit_clarification_answer_result(
        service.repository,
        answer_record_id=ANSWER_ID,
        organization_id=organization.organization_id,
        expected_revision_id=revision.revision_id,
        result=result,
        created_at=NOW,
    )

    restarted = PersistenceRepository(create_session_factory(engine))
    restored = get_clarification_answer_result(
        restarted,
        session_id=session.session_id,
        plan_content_hash=result.plan_content_hash,
        clarification_id=result.clarification_id,
        organization_id=organization.organization_id,
    )
    assert committed == restored == result
    expected = result.new_revision_id or revision.revision_id
    assert (
        restarted.get_current_revision(session.session_id, organization.organization_id).revision_id
        == expected
    )


def test_answer_revision_pointer_and_record_commit_atomically_and_retry_is_idempotent(
    engine, tmp_path
):
    service = build_service(engine)
    organization, session, revision, *_, cycle = _setup(service, tmp_path)
    result = _answer_result(
        session.session_id,
        revision,
        cycle,
        decision=ClarificationDecision.ACCEPT,
        outcome=ClarificationAnswerOutcome.APPLIED,
        reason=ClarificationAnswerReason.USER_ACCEPTED_PREFERENCE,
        changed=True,
    )

    first = commit_clarification_answer_result(
        service.repository,
        answer_record_id=ANSWER_ID,
        organization_id=organization.organization_id,
        expected_revision_id=revision.revision_id,
        result=result,
        created_at=NOW,
    )
    retry = commit_clarification_answer_result(
        service.repository,
        answer_record_id=uuid4(),
        organization_id=organization.organization_id,
        expected_revision_id=revision.revision_id,
        result=result,
        created_at=NOW,
    )

    assert first == retry == result
    assert (
        service.repository.get_current_revision(
            session.session_id, organization.organization_id
        ).revision_id
        == result.new_revision_id
    )
    assert (
        len(service.repository.list_revisions(session.session_id, organization.organization_id))
        == 2
    )


def test_answer_restoration_detects_relational_corruption(engine, tmp_path):
    service = build_service(engine)
    organization, session, revision, *_, cycle = _setup(service, tmp_path)
    result = _answer_result(
        session.session_id,
        revision,
        cycle,
        decision=ClarificationDecision.REJECT,
        outcome=ClarificationAnswerOutcome.REJECTED,
        reason=ClarificationAnswerReason.USER_REJECTED_OFFER,
    )
    commit_clarification_answer_result(
        service.repository,
        answer_record_id=ANSWER_ID,
        organization_id=organization.organization_id,
        expected_revision_id=revision.revision_id,
        result=result,
        created_at=NOW,
    )
    from jewelai_persistence.models import ClarificationAnswerRow

    with create_session_factory(engine).begin() as db:
        db.execute(
            update(ClarificationAnswerRow)
            .where(ClarificationAnswerRow.answer_record_id == ANSWER_ID)
            .values(content_hash="0" * 64)
        )
    with pytest.raises(ClarificationDecisionIntegrityError):
        service.repository.get_clarification_answer(
            session.session_id,
            result.plan_content_hash,
            result.clarification_id,
            organization.organization_id,
        )


def test_conflicting_stale_cross_scope_release_and_corrupt_answers_fail_closed(engine, tmp_path):
    service = build_service(engine)
    organization, session, revision, *_, cycle = _setup(service, tmp_path)
    result = _answer_result(
        session.session_id,
        revision,
        cycle,
        decision=ClarificationDecision.REJECT,
        outcome=ClarificationAnswerOutcome.REJECTED,
        reason=ClarificationAnswerReason.USER_REJECTED_OFFER,
    )
    commit_clarification_answer_result(
        service.repository,
        answer_record_id=ANSWER_ID,
        organization_id=organization.organization_id,
        expected_revision_id=revision.revision_id,
        result=result,
        created_at=NOW,
    )
    conflicting = result.model_copy(update={"answer_hash": "b" * 64, "content_hash": "c" * 64})
    payload = conflicting.model_dump(mode="json", exclude={"content_hash"})
    conflicting = ClarificationAnswerResult(
        **payload,
        content_hash=answer_hash(payload),
    )
    with pytest.raises(ClarificationDecisionConflictError):
        commit_clarification_answer_result(
            service.repository,
            answer_record_id=uuid4(),
            organization_id=organization.organization_id,
            expected_revision_id=revision.revision_id,
            result=conflicting,
            created_at=NOW,
        )
    with pytest.raises(OwnershipMismatchError):
        service.repository.get_clarification_answer(
            session.session_id, result.plan_content_hash, result.clarification_id, uuid4()
        )
    corrupt = result.model_dump(mode="json")
    corrupt["content_hash"] = "0" * 64
    with pytest.raises(ClarificationDecisionIntegrityError):
        service.repository.commit_clarification_answer(
            answer_record_id=uuid4(),
            session_id=session.session_id,
            organization_id=organization.organization_id,
            expected_revision_id=revision.revision_id,
            result_payload=corrupt,
            created_at=NOW,
        )
    mismatched = result.model_dump(mode="json")
    mismatched["knowledge_runtime_sha256"] = "0" * 64
    body = dict(mismatched)
    body.pop("content_hash")
    mismatched["content_hash"] = answer_hash(body)
    with pytest.raises(KnowledgeReleasePinConflictError):
        service.repository.commit_clarification_answer(
            answer_record_id=uuid4(),
            session_id=session.session_id,
            organization_id=organization.organization_id,
            expected_revision_id=revision.revision_id,
            result_payload=mismatched,
            created_at=NOW,
        )


def test_stale_answer_and_each_staged_answer_failure_roll_back_atomically(engine, tmp_path):
    service = build_service(engine)
    organization, session, revision, *_, cycle = _setup(service, tmp_path)
    applied = _answer_result(
        session.session_id,
        revision,
        cycle,
        decision=ClarificationDecision.ACCEPT,
        outcome=ClarificationAnswerOutcome.APPLIED,
        reason=ClarificationAnswerReason.USER_ACCEPTED_PREFERENCE,
        changed=True,
    )
    advanced = next_revision(revision, "emerald_cut")
    service.repository.append_revision_cas(
        session.session_id,
        organization.organization_id,
        revision.revision_id,
        advanced,
    )
    with pytest.raises(StaleRevisionError):
        commit_clarification_answer_result(
            service.repository,
            answer_record_id=ANSWER_ID,
            organization_id=organization.organization_id,
            expected_revision_id=revision.revision_id,
            result=applied,
            created_at=NOW,
        )
    assert (
        service.repository.list_clarification_answers(
            session.session_id, organization.organization_id
        )
        == ()
    )

    # Use a fresh session to exercise failures after the new revision has been staged.
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    revision = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    from jewelai_domain.knowledge_storage import KnowledgeArtifactStore

    store = KnowledgeArtifactStore(tmp_path / "answer-rollback")
    _, _, _, enrichment = _verified_result(store, revision)
    cycle = service.repository.create_enrichment_cycle(
        enrichment_cycle_id=uuid4(),
        session_id=session.session_id,
        organization_id=organization.organization_id,
        expected_revision_id=revision.revision_id,
        expected_previous_cycle_number=0,
        result=enrichment,
        created_at=NOW,
    )
    existing = _answer_result(
        session.session_id,
        revision,
        cycle,
        decision=ClarificationDecision.REJECT,
        outcome=ClarificationAnswerOutcome.REJECTED,
        reason=ClarificationAnswerReason.USER_REJECTED_OFFER,
    )
    commit_clarification_answer_result(
        service.repository,
        answer_record_id=ANSWER_ID,
        organization_id=organization.organization_id,
        expected_revision_id=revision.revision_id,
        result=existing,
        created_at=NOW,
    )
    changed = _changed_answer(
        _answer_result(
            session.session_id,
            revision,
            cycle,
            decision=ClarificationDecision.ACCEPT,
            outcome=ClarificationAnswerOutcome.APPLIED,
            reason=ClarificationAnswerReason.USER_ACCEPTED_PREFERENCE,
            changed=True,
        ),
        plan_content_hash="d" * 64,
        clarification_id="different-question",
    )
    with pytest.raises(ClarificationDecisionConflictError):
        commit_clarification_answer_result(
            service.repository,
            answer_record_id=ANSWER_ID,
            organization_id=organization.organization_id,
            expected_revision_id=revision.revision_id,
            result=changed,
            created_at=NOW,
        )
    assert (
        service.repository.get_current_revision(
            session.session_id, organization.organization_id
        ).revision_id
        == revision.revision_id
    )
    assert (
        len(service.repository.list_revisions(session.session_id, organization.organization_id))
        == 1
    )

    def fail_pointer(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("UPDATE DESIGN_SESSION"):
            raise RuntimeError("injected session pointer failure")

    event.listen(engine, "before_cursor_execute", fail_pointer)
    try:
        with pytest.raises(RuntimeError, match="injected session pointer failure"):
            commit_clarification_answer_result(
                service.repository,
                answer_record_id=uuid4(),
                organization_id=organization.organization_id,
                expected_revision_id=revision.revision_id,
                result=_changed_answer(
                    changed,
                    plan_content_hash="e" * 64,
                    clarification_id="pointer-failure-question",
                ),
                created_at=NOW,
            )
    finally:
        event.remove(engine, "before_cursor_execute", fail_pointer)
    assert (
        service.repository.get_current_revision(
            session.session_id, organization.organization_id
        ).revision_id
        == revision.revision_id
    )
    assert (
        len(service.repository.list_revisions(session.session_id, organization.organization_id))
        == 1
    )


def _correction_result(
    service,
    context,
    *,
    text="Change the center stone to emerald cut.",
    revision_override=None,
    prior_answers=(),
):
    organization, session, initial_revision, store, stored, report, active, cycle = context
    revision = revision_override or initial_revision
    request = UserCorrection(
        session_id=session.session_id,
        expected_revision_id=revision.revision_id,
        correction_text=text,
        locale="en",
        source=MessageSource(message_id="correction-1", recorded_at=NOW),
        previous_enrichment_cycle_id=cycle.enrichment_cycle_id,
        previous_enrichment_cycle_number=cycle.cycle_number,
        previous_enrichment_content_hash=cycle.result.content_hash,
        knowledge_package_id=stored.package_id,
        knowledge_artifact_version=stored.artifact_version,
        knowledge_runtime_sha256=active.runtime_sha256,
        knowledge_validation_report_sha256=report.sha256,
        dictionary_artifact_version=service.artifacts.dictionary.artifact_version,
        prompt_template_artifact_version=str(service.artifacts.prompts.artifact_version),
    )
    result = process_user_correction(
        request,
        authoritative_session_id=session.session_id,
        current_revision=revision,
        previous_cycle=cycle,
        prior_answer_results=prior_answers,
        dictionary=service.artifacts.dictionary,
        templates=service.artifacts.prompts,
        artifact_store=store,
        active_release=active,
        validation_report=report,
        created_at=NOW,
    )
    return organization, session, revision, result


def test_correction_persists_exact_committed_answer_lineage(engine, tmp_path):
    service = build_service(engine)
    context = _setup(service, tmp_path)
    organization, session, revision, *_, cycle = context
    answer = _answer_result(
        session.session_id,
        revision,
        cycle,
        decision=ClarificationDecision.ACCEPT,
        outcome=ClarificationAnswerOutcome.APPLIED,
        reason=ClarificationAnswerReason.USER_ACCEPTED_PREFERENCE,
        changed=True,
    )
    commit_clarification_answer_result(
        service.repository,
        answer_record_id=ANSWER_ID,
        organization_id=organization.organization_id,
        expected_revision_id=revision.revision_id,
        result=answer,
        created_at=NOW,
    )
    _, _, current, correction = _correction_result(
        service,
        context,
        revision_override=answer.resulting_revision,
        prior_answers=(answer,),
    )

    committed = commit_user_correction_result(
        service.repository,
        correction_record_id=CORRECTION_ID,
        next_enrichment_cycle_id=NEXT_CYCLE_ID,
        organization_id=organization.organization_id,
        expected_revision_id=current.revision_id,
        result=correction,
        created_at=NOW,
    )

    assert committed.prior_answer_results == (answer,)
    assert (
        get_user_correction_result(
            service.repository,
            session_id=session.session_id,
            correction_record_id=CORRECTION_ID,
            organization_id=organization.organization_id,
        )
        == correction
    )


@pytest.mark.parametrize(
    "text",
    [
        "Change the center stone to emerald cut.",
        "Keep the white gold.",
        "Do not use a halo.",
        "Change the unsupported clasp.",
    ],
)
def test_correction_outcomes_append_exactly_one_durable_cycle(engine, tmp_path, text):
    service = build_service(engine)
    context = _setup(service, tmp_path)
    organization, session, revision, result = _correction_result(service, context, text=text)

    committed = commit_user_correction_result(
        service.repository,
        correction_record_id=CORRECTION_ID,
        next_enrichment_cycle_id=NEXT_CYCLE_ID,
        organization_id=organization.organization_id,
        expected_revision_id=revision.revision_id,
        result=result,
        created_at=NOW,
    )
    retry = commit_user_correction_result(
        service.repository,
        correction_record_id=uuid4(),
        next_enrichment_cycle_id=uuid4(),
        organization_id=organization.organization_id,
        expected_revision_id=revision.revision_id,
        result=result,
        created_at=NOW,
    )

    assert committed == retry == result
    assert [
        cycle.cycle_number
        for cycle in service.repository.list_enrichment_cycles(
            session.session_id, organization.organization_id
        )
    ] == [1, 2]
    assert (
        len(
            service.repository.list_user_corrections(
                session.session_id, organization.organization_id
            )
        )
        == 1
    )
    current = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    assert current.revision_id == (result.new_revision_id or revision.revision_id)


def test_correction_stale_cycle_conflict_rolls_back_revision_pointer_and_history(engine, tmp_path):
    service = build_service(engine)
    context = _setup(service, tmp_path)
    organization, session, revision, result = _correction_result(service, context)
    other_organization, _, other_session = create_persisted_session(service)
    other_revision = service.repository.get_current_revision(
        other_session.session_id, other_organization.organization_id
    )
    from jewelai_domain.knowledge_storage import KnowledgeArtifactStore

    other_store = KnowledgeArtifactStore(tmp_path / "other-cycle")
    _, _, _, other_enrichment = _verified_result(other_store, other_revision)
    service.repository.create_enrichment_cycle(
        enrichment_cycle_id=NEXT_CYCLE_ID,
        session_id=other_session.session_id,
        organization_id=other_organization.organization_id,
        expected_revision_id=other_revision.revision_id,
        expected_previous_cycle_number=0,
        result=other_enrichment,
        created_at=NOW,
    )

    with pytest.raises(UserCorrectionConflictError):
        commit_user_correction_result(
            service.repository,
            correction_record_id=CORRECTION_ID,
            next_enrichment_cycle_id=NEXT_CYCLE_ID,
            organization_id=organization.organization_id,
            expected_revision_id=revision.revision_id,
            result=result,
            created_at=NOW,
        )

    assert (
        service.repository.get_current_revision(
            session.session_id, organization.organization_id
        ).revision_id
        == revision.revision_id
    )
    assert (
        len(service.repository.list_revisions(session.session_id, organization.organization_id))
        == 1
    )
    assert (
        len(
            service.repository.list_enrichment_cycles(
                session.session_id, organization.organization_id
            )
        )
        == 1
    )
    assert (
        service.repository.list_user_corrections(session.session_id, organization.organization_id)
        == ()
    )


def test_correction_restoration_detects_payload_and_relational_corruption(engine, tmp_path):
    service = build_service(engine)
    context = _setup(service, tmp_path)
    organization, session, revision, result = _correction_result(service, context)
    commit_user_correction_result(
        service.repository,
        correction_record_id=CORRECTION_ID,
        next_enrichment_cycle_id=NEXT_CYCLE_ID,
        organization_id=organization.organization_id,
        expected_revision_id=revision.revision_id,
        result=result,
        created_at=NOW,
    )
    restarted = PersistenceRepository(create_session_factory(engine))
    assert (
        get_user_correction_result(
            restarted,
            session_id=session.session_id,
            correction_record_id=CORRECTION_ID,
            organization_id=organization.organization_id,
        )
        == result
    )

    from jewelai_persistence.models import UserCorrectionRow

    with create_session_factory(engine).begin() as db:
        db.execute(
            update(UserCorrectionRow)
            .where(UserCorrectionRow.correction_record_id == CORRECTION_ID)
            .values(content_hash="0" * 64)
        )
    with pytest.raises(UserCorrectionIntegrityError):
        restarted.get_user_correction(
            session.session_id, CORRECTION_ID, organization.organization_id
        )


@pytest.mark.postgres
@pytest.mark.parametrize("conflicting", [False, True])
def test_postgres_concurrent_answers_are_idempotent_or_conflict(tmp_path, conflicting):
    database_url = os.getenv("TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("TEST_POSTGRES_URL is required for PostgreSQL decision concurrency coverage")
    engine = create_database_engine(database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        service = build_service(engine)
        organization, session, revision, *_, cycle = _setup(service, tmp_path)
        rejected = _answer_result(
            session.session_id,
            revision,
            cycle,
            decision=ClarificationDecision.REJECT,
            outcome=ClarificationAnswerOutcome.REJECTED,
            reason=ClarificationAnswerReason.USER_REJECTED_OFFER,
        )
        skipped = _answer_result(
            session.session_id,
            revision,
            cycle,
            decision=ClarificationDecision.SKIP,
            outcome=ClarificationAnswerOutcome.SKIPPED,
            reason=ClarificationAnswerReason.USER_SKIPPED,
        )
        second = skipped if conflicting else rejected

        def commit(result):
            repository = PersistenceRepository(create_session_factory(engine))
            return commit_clarification_answer_result(
                repository,
                answer_record_id=uuid4(),
                organization_id=organization.organization_id,
                expected_revision_id=revision.revision_id,
                result=result,
                created_at=NOW,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(commit, result) for result in (rejected, second)]
            outcomes = []
            for future in futures:
                try:
                    outcomes.append(future.result().decision)
                except ClarificationDecisionConflictError:
                    outcomes.append("conflict")
        assert outcomes.count("conflict") == int(conflicting)
        assert (
            len(
                service.repository.list_clarification_answers(
                    session.session_id, organization.organization_id
                )
            )
            == 1
        )
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.mark.postgres
@pytest.mark.parametrize("conflicting", [False, True])
def test_postgres_concurrent_corrections_are_idempotent_or_conflict(tmp_path, conflicting):
    database_url = os.getenv("TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("TEST_POSTGRES_URL is required for PostgreSQL correction concurrency coverage")
    engine = create_database_engine(database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        service = build_service(engine)
        context = _setup(service, tmp_path)
        organization, session, revision, first = _correction_result(
            service, context, text="Change the center stone to emerald cut."
        )
        *_, second = _correction_result(
            service,
            context,
            text=(
                "Change the center stone to round."
                if conflicting
                else "Change the center stone to emerald cut."
            ),
        )

        def commit(result):
            repository = PersistenceRepository(create_session_factory(engine))
            return commit_user_correction_result(
                repository,
                correction_record_id=uuid4(),
                next_enrichment_cycle_id=uuid4(),
                organization_id=organization.organization_id,
                expected_revision_id=revision.revision_id,
                result=result,
                created_at=NOW,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(commit, result) for result in (first, second)]
            outcomes = []
            for future in futures:
                try:
                    outcomes.append(future.result().semantic_hash)
                except UserCorrectionConflictError:
                    outcomes.append("conflict")
        assert outcomes.count("conflict") == int(conflicting)
        assert (
            len(
                service.repository.list_user_corrections(
                    session.session_id, organization.organization_id
                )
            )
            == 1
        )
        assert [
            cycle.cycle_number
            for cycle in service.repository.list_enrichment_cycles(
                session.session_id, organization.organization_id
            )
        ] == [1, 2]
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
