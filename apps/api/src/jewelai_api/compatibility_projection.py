"""Narrow F05 legacy-L proofs over strictly validated, unchanged native evidence."""

import hashlib
import re
from uuid import UUID

from jewelai_domain.clarification_state import evidence_hash
from jewelai_domain.compatibility import (
    AcceptedCompatibilityEvent,
    CausalCorrectionProof,
    CompatibilityBlockerRef,
    CompatibilityReadinessProjection,
    CompatibilityRecordRef,
    CompatibilitySourceSpan,
    ContextConsumedProof,
)
from jewelai_domain.continuation import ContinuationArtifactPins, ContinuationFrameCore
from jewelai_domain.models import Explicit, KnownValue, MessageSource, Unknown
from jewelai_domain.preservation import contract_hash
from jewelai_parser import parse_full_message

from .correction_enrichment import CorrectionReenrichmentResult
from .f04_planning import canonical_target
from .parsed_enrichment import proposed_design_for_transition


def _state(revision, target):
    value = revision.design
    for part in target.split("."):
        value = getattr(value, part)
    return value


def _revision_ref(revision):
    return CompatibilityRecordRef(id=revision.revision_id, hash=evidence_hash(revision))


def _verified_corrections(service, repo, native, sid, oid):
    """Actual legacy parse/proposal and accepted transition, never parser1.2."""
    verified = repo.restore_pinned_knowledge_runtime(
        sid,
        oid,
        service.artifact_store,
        active_release=service.active_release,
        validation_report=service.validation_report,
    )
    result = []
    for record in native.corrections:
        correction = CorrectionReenrichmentResult.model_validate(record.result_payload)
        message = repo.get_message(sid, UUID(correction.source.message_id), oid)
        before = repo.get_revision(sid, correction.previous_revision_id, oid)
        after = repo.get_revision(sid, correction.new_revision_id or before.revision_id, oid)
        parsed = parse_full_message(
            message.content,
            locale=native.session.locale,
            dictionary=service.artifacts.dictionary,
            knowledge_runtime=verified.compiled_runtime,
        )
        source = MessageSource(
            message_id=str(message.message_id), recorded_at=correction.source.recorded_at
        )
        if (
            message.actor != "user"
            or message.content != correction.correction_text
            or parsed != correction.parsed_correction
        ):
            raise ValueError("Retained correction source/parse mismatch")
        first = service._evaluate(before, parsed, source)
        if first != correction.correction_evaluation:
            raise ValueError("Retained correction ParserProposal/Matrix mismatch")
        proposed = proposed_design_for_transition(before, first)
        if correction.outcome == "APPLIED":
            if (
                after.parent_revision_id != before.revision_id
                or after.design != proposed
                or after.event.source != source
            ):
                raise ValueError("Retained correction has no actual accepted canonical transition")
        elif after != before:
            raise ValueError("Retained non-applied correction changed canonical state")
        post = service._evaluate(after, parsed, source)
        if (
            post != correction.post_transition_evaluation
            or after != correction.authoritative_revision
        ):
            raise ValueError("Retained correction post-state was modified")
        result.append((record, correction, before, after))
    return tuple(result)


def _actual_ancestry(repo, sid, oid, after, current):
    chain = []
    cursor = current
    seen = set()
    while cursor.revision_id != after.revision_id:
        if cursor.revision_id in seen or cursor.parent_revision_id is None:
            return None
        seen.add(cursor.revision_id)
        chain.append(cursor)
        cursor = repo.get_revision(sid, cursor.parent_revision_id, oid)
    return (after, *reversed(chain))


def causal_unknown_proofs(service, repo, native, sid, oid, verified_corrections=None):
    """Only required UNKNOWN whose exact gap was actually corrected can discharge."""
    corrections = verified_corrections or _verified_corrections(service, repo, native, sid, oid)
    plans = {r.content_hash: r for r in repo.list_clarification_plans(sid, oid)}
    proofs = []
    for record in native.answers:
        answer = record.result_payload
        if answer["decision"] != "UNKNOWN" or not answer["blocks_progression"]:
            continue
        plan = plans.get(answer["plan_content_hash"])
        if plan is None:
            raise ValueError("Original blocking UNKNOWN has no scoped plan")
        original = repo.get_revision(sid, UUID(answer["previous_revision_id"]), oid)
        target = answer["target"]
        if "*" in target or "[" in target or target.startswith("side_stones."):
            continue  # No invented concrete owner/group binding for a retained wildcard.
        prior = _state(original, target)
        if not (prior is None or isinstance(prior, Unknown) and prior.requirement == "required"):
            continue
        question = next(
            (
                q
                for q in plan.plan_payload["questions"]
                if q["clarification_id"] == answer["clarification_id"]
            ),
            None,
        )
        if question is None or question["target"] != target or question["importance"] != "blocking":
            continue
        for cr, correction, before, after in corrections:
            if correction.outcome != "APPLIED" or before.revision < original.revision:
                continue
            previous = _state(before, target)
            if previous is not None and not isinstance(previous, Unknown):
                continue
            updates = [
                u
                for u in correction.correction_evaluation.parser_proposal.accepted_updates
                if u.concrete_target == target
            ]
            accepted = _state(after, target)
            current = _state(native.snapshot.revision, target)
            if (
                not updates
                or not isinstance(accepted, Explicit)
                or not isinstance(current, Explicit)
            ):
                continue
            if current.value != accepted.value or current.source != accepted.source:
                continue
            ancestry = _actual_ancestry(repo, sid, oid, after, native.snapshot.revision)
            if ancestry is None or any(
                not isinstance(_state(r, target), KnownValue)
                or _state(r, target).value != accepted.value
                for r in ancestry
            ):
                continue
            payload = dict(
                kind="accepted_target_replaces_unknown",
                original_answer_ref=CompatibilityRecordRef(
                    id=record.answer_record_id, hash=record.content_hash
                ),
                original_plan_ref=CompatibilityRecordRef(
                    id=plan.clarification_plan_id, hash=plan.content_hash
                ),
                target=canonical_target(
                    native.snapshot.revision, target, scope=native.protection.scope
                ),
                accepted_event_ref=AcceptedCompatibilityEvent(
                    kind="correction",
                    record_id=cr.correction_record_id,
                    content_hash=cr.content_hash,
                ),
                source_message_id=UUID(correction.source.message_id),
                source_parse_hash=evidence_hash(correction.parsed_correction),
                before_revision_ref=_revision_ref(before),
                after_revision_ref=_revision_ref(after),
                current_state_sha256=evidence_hash(current),
                ancestry_refs=tuple(_revision_ref(r) for r in ancestry),
            )
            proofs.append(
                CausalCorrectionProof(
                    **payload,
                    content_hash=contract_hash("jewelai.CausalCorrectionProof/1.0.0", payload),
                )
            )
            break
    return tuple(proofs)


_OWNER_TOKENS = frozenset(
    (
        "metal",
        "metals",
        "металл",
        "металла",
        "металлу",
        "металлом",
        "металле",
        "металлы",
        "металлов",
        "металлам",
        "металлами",
        "металлах",
    )
)
_UNSAFE_CLAUSE = re.compile(r"\b(?:or|или|maybe|perhaps|возможно|no|not|не|без)\b", re.I)
_CLAUSE_BREAK = re.compile(r"[.!?;\n]")


def context_consumption_proofs(service, repo, native, sid, oid, verified_corrections=None):
    corrections = verified_corrections or _verified_corrections(service, repo, native, sid, oid)
    proofs = []
    covered_records = set()
    for record, correction, _before, after in corrections:
        if (
            correction.outcome == "REJECTED"
            or correction.correction_evaluation.parser_proposal.issues
        ):
            continue
        candidates = correction.parsed_correction.candidates
        text = correction.correction_text
        accepted = []
        for candidate in candidates:
            if (
                candidate.target not in {"metal.color", "metal.material", "metal.purity"}
                or candidate.subject != "product_body"
                or candidate.classification != "requirement"
                or candidate.certainty != "explicit"
                or candidate.normalization_source != "domain_dictionary"
                or candidate.parser_update is None
            ):
                continue
            state = _state(after, candidate.target.value)
            if isinstance(state, Explicit) and candidate.normalized_values == (state.value,):
                accepted.append(candidate)
        covered = set()
        for residual in candidates:
            if (
                residual.target is not None
                or residual.classification != "requirement"
                or residual.subject != "product_body"
            ):
                continue
            for candidate in accepted:
                span = candidate.evidence
                owner = residual.evidence.text.casefold() in _OWNER_TOKENS
                mirror = (
                    residual.evidence == span
                    and residual.normalized_values == candidate.normalized_values
                    and residual.normalization_source == "knowledge_library"
                )
                if not (owner or mirror):
                    continue
                left = 0
                right = len(text)
                for boundary in _CLAUSE_BREAK.finditer(text):
                    if boundary.end() <= span.start:
                        left = boundary.end()
                    elif boundary.start() >= span.end:
                        right = boundary.start()
                        break
                if not (left <= residual.evidence.start < residual.evidence.end <= right):
                    continue
                clause = text[left:right]
                if _UNSAFE_CLAUSE.search(clause):
                    continue
                # Full clause must be the accepted value span plus approved owner
                # tokens/articles, not an independently requested second object.
                remaining = text[left : span.start] + text[span.end : right]
                words = re.findall(r"[^\W\d_]+", remaining, flags=re.UNICODE)
                if not words or any(
                    w.casefold() not in _OWNER_TOKENS | {"a", "an", "the"} for w in words
                ):
                    continue
                if not any(w.casefold() in _OWNER_TOKENS for w in words):
                    continue
                target = candidate.target.value
                payload = dict(
                    kind="context_owner_token_consumed",
                    original_correction_ref=CompatibilityRecordRef(
                        id=record.correction_record_id, hash=record.content_hash
                    ),
                    original_parse_hash=evidence_hash(correction.parsed_correction),
                    residual_candidate_id=residual.candidate_id,
                    residual_span=CompatibilitySourceSpan(
                        start=residual.evidence.start,
                        end=residual.evidence.end,
                        text_sha256=hashlib.sha256(
                            residual.evidence.text.encode("utf-8")
                        ).hexdigest(),
                    ),
                    accepted_candidate_ids=(candidate.candidate_id,),
                    accepted_target=canonical_target(after, target, scope=native.protection.scope),
                    accepted_value_sha256=evidence_hash(_state(after, target).value),
                    source_message_id=UUID(correction.source.message_id),
                    context_classifier_version="1.0.0",
                    current_state_sha256=evidence_hash(_state(native.snapshot.revision, target)),
                )
                proofs.append(
                    ContextConsumedProof(
                        **payload,
                        content_hash=contract_hash("jewelai.ContextConsumedProof/1.0.0", payload),
                    )
                )
                covered.add(residual.candidate_id)
                break
        deferred = {
            d.candidate.candidate_id
            for d in correction.correction_evaluation.dispositions
            if d.outcome == "DEFERRED"
        }
        if deferred and deferred.issubset(covered):
            covered_records.add(record.content_hash)
    return tuple(proofs), frozenset(covered_records)


def project_legacy_readiness(service, repo, native, sid, oid):
    if (native.session.question_artifact_version, native.session.rules_artifact_version) != (
        "1.0.0",
        "1.0.0",
    ):
        raise ValueError("Legacy-L compatibility cannot change the retained F profile")
    service = service._for_session(sid, oid, repository=repo)
    verified = _verified_corrections(service, repo, native, sid, oid)
    causal = causal_unknown_proofs(service, repo, native, sid, oid, verified)
    contextual, covered = context_consumption_proofs(service, repo, native, sid, oid, verified)
    discharged = {p.original_answer_ref.hash for p in causal} | set(covered)
    remaining = tuple(
        CompatibilityBlockerRef(kind=d.kind, id=d.decision_id, hash=d.content_hash)
        for d in native.snapshot.decision_lineage
        if d.blocks_progression and d.content_hash not in discharged
    )
    hashes = dict(service.artifacts.artifact_hashes)
    pins = ContinuationArtifactPins(
        design_schema_version=native.snapshot.revision.schema_version,
        role_artifact_version=native.session.role_artifact_version,
        dictionary_artifact_version=native.session.dictionary_artifact_version,
        question_schema_version=native.session.question_artifact_version,
        question_artifact_version=native.session.question_artifact_version,
        rules_schema_version=native.session.rules_artifact_version,
        rules_artifact_version=native.session.rules_artifact_version,
        prompt_template_artifact_version=native.session.prompt_artifact_version,
        dictionary_sha256=hashes["dictionary"],
        question_sha256=hashes["questions"],
        rules_sha256=hashes["rules"],
    )
    payload = dict(
        schema_version="1.0.0",
        projection_id="jewelai.legacy-l.compat/1.0.0",
        scope=native.protection.scope,
        build_mode="read_only_output",
        current_frame_core=ContinuationFrameCore(
            **native.frame.model_dump(exclude={"plan_hash", "history_root_sha256"})
        ),
        evidence_head=native.frame,
        retained_artifact_pins=pins,
        legacy_history_root_sha256=native.frame.history_root_sha256,
        proofs=tuple(sorted((*causal, *contextual), key=lambda p: p.content_hash)),
        remaining_blocker_refs=tuple(sorted(remaining, key=lambda p: (p.kind, p.id, p.hash))),
    )
    return CompatibilityReadinessProjection(
        **payload,
        content_hash=contract_hash("jewelai.CompatibilityReadinessProjection/1.0.0", payload),
    )
