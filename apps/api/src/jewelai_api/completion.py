"""Opt-in durable completion. Source reads/build/append share one session-first lock."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from jewelai_domain.clarification_state import Sha256, StrictEvidenceModel
from jewelai_domain.continuation import ContinuationFrame
from jewelai_domain.preservation import contract_hash
from jewelai_persistence.completion import (
    CompletionStorageConflict,
    CompletionStorageUnavailable,
    completion_transaction,
)
from jewelai_persistence.models import PromptCompletionRow
from jewelai_prompts.completion import (
    CompletionRegistry,
    InternalFinalPromptV6,
    build_completion,
    validate_completion,
)
from jewelai_prompts.final_prompt_v4 import FinalPromptSnapshotV3

from .continuation_preview import ContinuationReadError, read_preview


class CompleteRequest(StrictEvidenceModel):
    schema_version: Literal["1.0.0"]
    request_id: UUID
    message_id: UUID
    expected_frame: ContinuationFrame
    anything_else: Literal["YES", "NO"]


class CompletionQuestion(StrictEvidenceModel):
    question_id: Literal["ANYTHING_ELSE/1.0.0"] = "ANYTHING_ELSE/1.0.0"
    text: str
    choices: tuple[Literal["YES", "NO"], ...] = ("YES", "NO")


def completion_question(locale):
    return CompletionQuestion(
        text="Хотите добавить что-нибудь ещё?"
        if locale == "ru"
        else "Anything else you would like to add?"
    )


class CompletionContext(StrictEvidenceModel):
    schema_version: Literal["completion-context/1.0.0"] = "completion-context/1.0.0"
    status: Literal["AWAITING_COMPLETION"] = "AWAITING_COMPLETION"
    expected_frame: ContinuationFrame
    question: CompletionQuestion


class CompletionResponse(StrictEvidenceModel):
    schema_version: Literal["1.0.0"]
    completion_id: UUID
    status: Literal["FINAL", "EDITING"]
    is_current: bool
    replayed: bool
    expected_frame: ContinuationFrame
    final_prompt: InternalFinalPromptV6 | None
    content_hash: Sha256
    question: CompletionQuestion


def load_registry(path: Path, expected_sha256: str):
    registry = CompletionRegistry.model_validate_json(path.read_bytes())
    if registry.review_status != "APPROVED":
        raise ValueError("Completion registry requires explicit reviewed approval")
    if registry.sha256 != expected_sha256:
        raise ValueError("Completion registry SHA-256 binding mismatch")
    return registry


class CompletionService:
    def __init__(self, service, registry, *, clock=None):
        registry = CompletionRegistry.model_validate_json(registry.model_dump_json())
        if registry.review_status != "APPROVED":
            raise ValueError("Completion registry requires explicit reviewed approval")
        self.service, self.registry = service, registry
        self.clock = clock or (lambda: datetime.now(UTC))

    def _snapshot(self, repo, sid, oid):
        return read_preview(
            self.service,
            sid,
            oid,
            _repository=repo,
            _consume=lambda snapshot, bound, pending, facts: (snapshot, bound, pending, facts),
        )

    def _validate(self, row, repo, sid, oid):
        payload = row.payload
        if contract_hash("jewelai.CompletionRecord/1", payload) != row.content_hash:
            raise ContinuationReadError(
                500, "invalid_completion_history", "Stored completion integrity failed"
            )
        try:
            request = CompleteRequest.model_validate(payload["request"])
            snapshot = FinalPromptSnapshotV3.model_validate(payload["snapshot"])
            message = repo.get_message(sid, row.message_id, oid)
            revision = repo.get_revision(sid, row.revision_id, oid)
            cycle = repo.get_enrichment_cycle(sid, row.cycle_id, oid)
            if (
                snapshot.revision != revision
                or cycle.result != snapshot.enrichment_result
                or cycle.result.content_hash != snapshot.current_frame.enrichment_result_hash
                or row.message_id != request.message_id
                or row.request_id != request.request_id
                or row.revision_id != snapshot.revision.revision_id
                or row.cycle_id != snapshot.enrichment_cycle_id
                or request.expected_frame != snapshot.current_frame
                or snapshot.session_id != sid
                or snapshot.organization_id != oid
                or payload["principal_id"] != str(row.principal_id)
                or hashlib.sha256(message.content.encode()).hexdigest() != payload["message_sha256"]
                or row.request_hash
                != contract_hash(
                    "jewelai.CompletionRequest/1",
                    dict(request=request, principal_id=row.principal_id),
                )
            ):
                raise ValueError("Completion source binding mismatch")
            bound = self.service._for_session(sid, oid, repository=repo)
            final = payload["final_prompt"]
            registry = CompletionRegistry.model_validate(payload["registry"])
            if registry.review_status != "APPROVED":
                raise ValueError("Unapproved stored registry")
            if request.anything_else == "NO":
                validated = validate_completion(final, bound.artifacts.prompts)
                rebuilt = build_completion(
                    snapshot,
                    registry,
                    completion_id=row.completion_id,
                    message_id=row.message_id,
                    completed_at=self.service.repository._utc(row.created_at),
                    dictionary=bound.artifacts.dictionary,
                    templates=bound.artifacts.prompts,
                    source_facts=payload["source_facts"],
                    pending_descriptions=payload["pending"],
                )
                if validated != rebuilt:
                    raise ValueError("Completion reconstruction mismatch")
            elif final is not None:
                raise ValueError("YES cannot finalize")
            return request, payload
        except ContinuationReadError:
            raise
        except ValueError:
            raise ContinuationReadError(
                500, "invalid_completion_history", "Stored completion source failed validation"
            ) from None

    def execute(self, sid, oid, principal, request):
        request_hash = contract_hash(
            "jewelai.CompletionRequest/1", dict(request=request, principal_id=principal)
        )

        def operation(db, repo, session, rows):
            current, bound, pending, facts = self._snapshot(repo, sid, oid)
            previous = next((r for r in rows if r.request_id == request.request_id), None)
            if previous:
                if previous.request_hash != request_hash:
                    raise ContinuationReadError(
                        409, "idempotency_conflict", "Completion request ID was reused"
                    )
                _, payload = self._validate(previous, repo, sid, oid)
                return self._response(
                    previous,
                    payload,
                    True,
                    current.current_frame == request.expected_frame
                    and rows[-1].completion_id == previous.completion_id,
                )
            if request.expected_frame != current.current_frame:
                raise ContinuationReadError(409, "stale_completion_frame", "Current design changed")
            message = repo.get_message(sid, request.message_id, oid)
            allowed = {"YES": {"yes", "да"}, "NO": {"no", "нет"}}[request.anything_else]
            if message.actor != "user" or message.content.strip().casefold() not in allowed:
                raise ContinuationReadError(
                    422, "invalid_completion_intent", "Store an explicit YES or NO user Message"
                )
            now = self.clock()
            completion_id = uuid4()
            final = None
            if request.anything_else == "NO":
                try:
                    final = build_completion(
                        current,
                        self.registry,
                        completion_id=completion_id,
                        message_id=request.message_id,
                        completed_at=now,
                        dictionary=bound.artifacts.dictionary,
                        templates=bound.artifacts.prompts,
                        source_facts=facts,
                        pending_descriptions=pending,
                    )
                    validate_completion(final, bound.artifacts.prompts)
                except ValueError as e:
                    code = (
                        str(e)
                        if str(e)
                        in {
                            "pending_keep_consent",
                            "mandatory_decision_unresolved",
                            "conflicting_evidence",
                        }
                        else "completion_validation_failed"
                    )
                    raise ContinuationReadError(
                        409,
                        code,
                        "Completion requires resolution of protected or mandatory decisions",
                    ) from None
            payload = dict(
                schema_version="1.0.0",
                request=request.model_dump(mode="json"),
                principal_id=str(principal),
                snapshot=current.model_dump(mode="json"),
                registry=self.registry.model_dump(mode="json"),
                pending=pending,
                source_facts=facts,
                message_sha256=hashlib.sha256(message.content.encode()).hexdigest(),
                final_prompt=final.model_dump(mode="json") if final else None,
            )
            # Normalize exactly what JSON storage will retain (UUID-free source keys).
            import json

            from jewelai_domain.clarification_state import evidence_bytes

            payload = json.loads(evidence_bytes(payload))
            row = PromptCompletionRow(
                completion_id=completion_id,
                organization_id=oid,
                session_id=sid,
                revision_id=current.revision.revision_id,
                cycle_id=current.enrichment_cycle_id,
                message_id=request.message_id,
                principal_id=principal,
                request_id=request.request_id,
                request_hash=request_hash,
                sequence_number=len(rows) + 1,
                payload=payload,
                content_hash=contract_hash("jewelai.CompletionRecord/1", payload),
                created_at=now,
            )
            db.add(row)
            db.flush()
            self._validate(
                row, repo, sid, oid
            )  # Fail before commit, never after partial persistence.
            return self._response(row, payload, False, True)

        return self._transaction(sid, oid, principal, operation)

    def current(self, sid, oid, principal):
        def operation(db, repo, session, rows):
            snapshot, *_ = self._snapshot(repo, sid, oid)
            if not rows:
                return CompletionContext(
                    expected_frame=snapshot.current_frame,
                    question=completion_question(snapshot.locale),
                )
            row = rows[-1]
            request, payload = self._validate(row, repo, sid, oid)
            if request.expected_frame != snapshot.current_frame:
                raise ContinuationReadError(
                    409, "completion_invalidated", "Design changed; confirm completion again"
                )
            return self._response(row, payload, False, True)

        return self._transaction(sid, oid, principal, operation, write=False)

    def _transaction(self, sid, oid, principal, operation, **kwargs):
        try:
            return completion_transaction(
                self.service.repository, sid, oid, principal, operation, **kwargs
            )
        except CompletionStorageUnavailable:
            raise ContinuationReadError(
                503, "completion_storage_unavailable", "Completion storage is unavailable"
            ) from None
        except CompletionStorageConflict:
            raise ContinuationReadError(
                409,
                "completion_transaction_conflict",
                "Retry the same request after reading current state",
            ) from None

    @staticmethod
    def _response(row, payload, replayed, current):
        return CompletionResponse(
            schema_version="1.0.0",
            completion_id=str(row.completion_id),
            status="FINAL" if payload["final_prompt"] else "EDITING",
            is_current=current,
            replayed=replayed,
            expected_frame=payload["request"]["expected_frame"],
            final_prompt=payload["final_prompt"],
            content_hash=row.content_hash,
            question=completion_question(payload["snapshot"]["locale"]),
        )
