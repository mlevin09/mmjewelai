"""Atomic, scoped preparation retention. No provider, dispatch or application dependencies."""

import hashlib
from contextlib import nullcontext

from jewelai_auth import MembershipNotFoundError
from jewelai_prompts import GenerationPreparation
from jewelai_prompts.downstream_preparation import canonical_bytes
from jewelai_prompts.enrichment import enrichment_template_version
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .models import (
    ClarificationAnswerRow,
    ClarificationPlanRow,
    EnrichmentCycleRow,
    GenerationCommandRow,
    GenerationPreparationRow,
    OrganizationMembershipRow,
    OrganizationRow,
    SpecificationRevisionRow,
    UserCorrectionRow,
)
from .repository import NotFoundError, PersistenceError, PersistenceRepository


class PreparationConflictError(PersistenceError):
    def __init__(self, code="idempotency_conflict"):
        self.code = code
        super().__init__(code)


class PreparationIntegrityError(PersistenceError):
    pass


class PreparationStorageError(PersistenceError):
    pass


class _LockedReadFactory:
    """Reuse the already locked SQLAlchemy Session; never enter/close a second session."""

    def __init__(self, db):
        self.db = db

    def __call__(self):
        return nullcontext(self.db)

    def begin(self):
        raise RuntimeError("A locked source reader cannot start a write transaction")


def locked_reader(db):
    return PersistenceRepository(_LockedReadFactory(db))


def _authorize_and_lock(repository, db, organization_id, session_id, principal_id):
    # NO KEY UPDATE still serializes with membership mutation's FOR UPDATE, but allows the
    # FK KEY SHARE taken by session-first correction/answer writers. UPDATE would deadlock.
    organization = db.scalar(
        select(OrganizationRow)
        .where(OrganizationRow.organization_id == organization_id)
        .with_for_update(key_share=True)
    )
    membership = db.get(OrganizationMembershipRow, (organization_id, principal_id))
    if organization is None or membership is None:
        raise MembershipNotFoundError("Organization membership not found")
    session = db.scalar(
        repository._scoped_session_query(session_id, organization_id).with_for_update()
    )
    if session is None:
        raise NotFoundError("Session not found")
    return session


def _summary(preparation):
    payload = preparation.payload
    source = payload.source_handoff
    return {
        "schema_version": "1.0.0",
        "preparation_id": str(payload.preparation_id),
        "session_id": str(payload.session_id),
        "product_state_revision_id": str(payload.product_state_revision_id),
        "enrichment_cycle_id": str(payload.enrichment_cycle_id),
        "enrichment_cycle_number": payload.enrichment_cycle_number,
        "source_handoff_hash": payload.source_handoff_hash,
        "artifact_hash": payload.artifact_hash,
        "rendering_hash": payload.execution.rendering_hash,
        "readiness": source.readiness.value,
        "unresolved_summary": list(source.internal_final_prompt.description.unresolved_summary),
        "created_at": payload.model_dump(mode="json")["created_at"],
    }


def _validate_row(repository, db, session, row):
    """Validate both exact frozen bytes and their real historical relational bindings."""
    try:
        preparation = GenerationPreparation(row.artifact_bytes)
        p = preparation.payload
        mirrored = (
            "preparation_id",
            "organization_id",
            "session_id",
            "design_id",
            "product_state_revision_id",
            "enrichment_cycle_id",
            "enrichment_cycle_number",
            "enrichment_result_hash",
            "schema_version",
            "source_handoff_hash",
            "source_bytes_sha256",
            "gate_evidence_hash",
            "artifact_hash",
        )
        if (
            any(getattr(row, field) != getattr(p, field) for field in mirrored)
            or row.project_id != session.project_id
            or row.rendering_hash != p.execution.rendering_hash
            or row.source_bytes != canonical_bytes(p.source_handoff)
            or canonical_bytes(row.artifact_payload) != row.artifact_bytes
            or repository._utc(row.created_at) != p.created_at
        ):
            raise ValueError("preparation mirror mismatch")
        revision = db.get(SpecificationRevisionRow, row.product_state_revision_id)
        cycle = db.get(EnrichmentCycleRow, row.enrichment_cycle_id)
        if revision is None or cycle is None:
            raise ValueError("missing source")
        if (
            revision.session_id != row.session_id
            or revision.design_id != row.design_id
            or canonical_bytes(revision.snapshot) != canonical_bytes(p.gate_evidence.revision)
            or cycle.session_id != row.session_id
            or cycle.specification_revision_id != row.product_state_revision_id
            or cycle.cycle_number != row.enrichment_cycle_number
        ):
            raise ValueError("source binding mismatch")
        verified_cycle = repository._enrichment_cycle_record(
            cycle, repository._knowledge_release_pin(session)
        )
        if verified_cycle.result.content_hash != p.enrichment_result_hash:
            raise ValueError("cycle hash mismatch")
        pin = verified_cycle.release_pin
        expected_release = {
            "package_id": pin.package_id,
            "artifact_version": pin.artifact_version,
            "runtime_sha256": pin.runtime_sha256,
            "validation_report_sha256": pin.validation_report_sha256,
        }
        prompt = p.source_handoff.internal_final_prompt
        if any(
            release.model_dump(mode="json") != expected_release
            for release in (
                p.source_handoff.knowledge_release,
                prompt.knowledge_release,
                p.gate_evidence.knowledge_release,
            )
        ):
            raise ValueError("historical Knowledge identity mismatch")
        plan = db.get(ClarificationPlanRow, p.gate_evidence.clarification_plan_id)
        if (
            plan is None
            or plan.session_id != row.session_id
            or plan.enrichment_cycle_id != row.enrichment_cycle_id
        ):
            raise ValueError("plan scope mismatch")
        verified_plan = repository._clarification_plan_record(db, plan, session)
        # Bind retained versions to this historical cycle/plan, not the latest mutable cycle.
        versions = prompt.artifact_versions
        if (
            versions.enrichment_version != verified_cycle.result.enrichment_version
            or versions.prompt_template_artifact_version
            != enrichment_template_version(verified_cycle.result)
            or versions.dictionary_artifact_version != plan.dictionary_artifact_version
            or versions.question_artifact_version != plan.question_artifact_version
            or versions.rules_artifact_version != plan.rules_artifact_version
        ):
            raise ValueError("historical artifact versions mismatch")
        if verified_plan.content_hash != p.gate_evidence.clarification_plan_hash or canonical_bytes(
            verified_plan.plan_payload["constraint_evidence"]
        ) != canonical_bytes(
            [
                item.model_dump(mode="json")
                for item in p.source_handoff.internal_final_prompt.constraint_evidence
            ]
        ):
            raise ValueError("plan binding mismatch")
        for refs, model, id_field in (
            (p.gate_evidence.decision_frontier.answers, ClarificationAnswerRow, "answer_record_id"),
            (
                p.gate_evidence.decision_frontier.corrections,
                UserCorrectionRow,
                "correction_record_id",
            ),
        ):
            for ref in refs:
                record = db.get(model, ref.record_id)
                if record is None or record.session_id != row.session_id:
                    raise ValueError("frontier scope mismatch")
                result = repository._verified_payload_hash(
                    record.result_payload,
                    hash_field="content_hash",
                    error_type=PreparationIntegrityError,
                )
                if (
                    result["content_hash"] != ref.content_hash
                    or getattr(record, id_field) != ref.record_id
                ):
                    raise ValueError("frontier hash mismatch")
        return preparation
    except (ValueError, KeyError, TypeError) as exc:
        raise PreparationIntegrityError("Stored preparation failed integrity validation") from exc


def commit_preparation(
    repository, *, organization_id, session_id, principal_id, idempotency_key, request_hash, builder
):
    """Authorize/replay/lock/re-read/build/persist, with exactly one transaction boundary."""
    try:
        with repository._session_factory.begin() as db:
            session = _authorize_and_lock(repository, db, organization_id, session_id, principal_id)
            key = (organization_id, session_id, "prepare_generation", idempotency_key)
            command = db.get(GenerationCommandRow, key)
            if command is not None:
                if command.request_hash != request_hash:
                    raise PreparationConflictError()
                row = db.get(GenerationPreparationRow, command.preparation_id)
                if (
                    row is None
                    or row.organization_id != organization_id
                    or row.session_id != session_id
                ):
                    raise PreparationIntegrityError("Committed command has invalid scope")
                frozen = _summary(_validate_row(repository, db, session, row))
                if (
                    canonical_bytes(frozen) != command.response_bytes
                    or hashlib.sha256(command.response_bytes).hexdigest() != command.response_hash
                ):
                    raise PreparationIntegrityError(
                        "Committed response failed integrity validation"
                    )
                return frozen, True
            preparation = builder(locked_reader(db))
            p = preparation.payload
            if (
                p.organization_id != organization_id
                or p.session_id != session_id
                or p.product_state_revision_id != session.current_revision_id
            ):
                raise PreparationConflictError("preparation_stale")
            # A server callback still cannot commit an artifact for a stale cycle.
            latest = db.scalar(
                select(EnrichmentCycleRow)
                .where(EnrichmentCycleRow.session_id == session_id)
                .order_by(EnrichmentCycleRow.cycle_number.desc())
                .limit(1)
            )
            if latest is None or (
                p.enrichment_cycle_id,
                p.enrichment_cycle_number,
                p.enrichment_result_hash,
            ) != (latest.enrichment_cycle_id, latest.cycle_number, latest.content_hash):
                raise PreparationConflictError("enrichment_cycle_mismatch")
            mirrored = {
                field: getattr(p, field)
                for field in (
                    "preparation_id",
                    "organization_id",
                    "session_id",
                    "design_id",
                    "product_state_revision_id",
                    "enrichment_cycle_id",
                    "enrichment_cycle_number",
                    "enrichment_result_hash",
                    "schema_version",
                    "source_handoff_hash",
                    "source_bytes_sha256",
                    "gate_evidence_hash",
                    "artifact_hash",
                    "created_at",
                )
            }
            row = GenerationPreparationRow(
                **mirrored,
                project_id=session.project_id,
                rendering_hash=p.execution.rendering_hash,
                source_bytes=canonical_bytes(p.source_handoff),
                artifact_bytes=preparation.canonical,
                artifact_payload=preparation.model_dump(),
            )
            db.add(row)
            db.flush()
            _validate_row(repository, db, session, row)
            response = _summary(preparation)
            response_bytes = canonical_bytes(response)
            db.add(
                GenerationCommandRow(
                    organization_id=organization_id,
                    session_id=session_id,
                    command="prepare_generation",
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    preparation_id=p.preparation_id,
                    response_bytes=response_bytes,
                    response_hash=hashlib.sha256(response_bytes).hexdigest(),
                    created_at=p.created_at,
                )
            )
            db.flush()
        return response, False
    except SQLAlchemyError:
        raise PreparationStorageError("Generation preparation storage is unavailable") from None


def read_preparation(repository, *, organization_id, session_id, principal_id, preparation_id):
    try:
        with repository._session_factory.begin() as db:
            session = _authorize_and_lock(repository, db, organization_id, session_id, principal_id)
            row = db.scalar(
                select(GenerationPreparationRow).where(
                    GenerationPreparationRow.preparation_id == preparation_id,
                    GenerationPreparationRow.organization_id == organization_id,
                    GenerationPreparationRow.session_id == session_id,
                )
            )
            if row is None:
                raise NotFoundError("Preparation not found")
            return _summary(_validate_row(repository, db, session, row))
    except SQLAlchemyError:
        raise PreparationStorageError("Generation preparation storage is unavailable") from None
