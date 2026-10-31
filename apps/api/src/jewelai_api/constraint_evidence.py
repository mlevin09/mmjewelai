"""Deterministic preservation of explicit non-schema constraint evidence."""

import hashlib
import json
from collections.abc import Callable
from uuid import UUID

from jewelai_domain.models import MessageSource
from jewelai_domain.models_v1_1 import AnyDesignRevision, validate_design_revision
from jewelai_parser import (
    CandidateCertainty,
    CandidateClassification,
)
from jewelai_parser.full_message import _ownership_context
from jewelai_prompts import FinalPromptConstraintEvidence, project_revision

from .clarification import _TARGET_QUESTION
from .parsed_enrichment import CandidateDispositionOutcome, ParsedCandidateEnrichmentResult


class ConstraintEvidenceIntegrityError(ValueError):
    """Canonical preservation cannot be reconciled with its immutable source."""


_INSTRUCTIONS = {
    ("feature.halo", "prohibition", "en"): "Do not include a halo.",
    ("feature.halo", "prohibition", "ru"): "Не добавлять гало.",
    ("feature.halo", "requirement", "en"): "Include a halo.",
    ("feature.halo", "requirement", "ru"): "Добавить гало.",
    ("feature.engraving", "prohibition", "en"): "Do not include engraving.",
    ("feature.engraving", "prohibition", "ru"): "Не добавлять гравировку.",
    ("feature.side_stones", "prohibition", "en"): "Do not include side stones.",
    ("feature.side_stones", "prohibition", "ru"): "Не добавлять боковые камни.",
    ("component.center_stone", "preservation", "en"): ("Keep the existing center stone unchanged."),
    ("component.center_stone", "preservation", "ru"): (
        "Сохранить существующий центральный камень без изменений."
    ),
    ("component.band", "preservation", "en"): "Keep the existing band unchanged.",
    ("component.band", "preservation", "ru"): "Сохранить существующую шинку без изменений.",
    (
        "composition.symmetry_mode",
        "requirement",
        "en",
    ): "Use the explicitly requested asymmetrical composition.",
    (
        "composition.symmetry_mode",
        "requirement",
        "ru",
    ): "Использовать явно заданную асимметричную композицию.",
    ("composition.symmetry_mode", "preservation", "ru"): (
        "Сохранить явно заданную асимметричную композицию; не выравнивать её."
    ),
    ("composition.symmetry_mode", "preservation", "en"): (
        "Preserve the explicitly requested asymmetrical composition; do not make it symmetrical."
    ),
    ("design.proportions", "preservation", "en"): "Keep the existing proportions unchanged.",
    ("design.proportions", "preservation", "ru"): (
        "Сохранить существующие пропорции без изменений."
    ),
}


def merge_constraint_evidence(
    enrichment: ParsedCandidateEnrichmentResult,
    *,
    session_id: UUID,
    organization_id: UUID,
    source: MessageSource,
    authoritative_revision: AnyDesignRevision | object,
    enrichment_cycle_id: UUID,
    previous: tuple[FinalPromptConstraintEvidence, ...] = (),
    load_source_revision: Callable[[UUID], AnyDesignRevision] | None = None,
) -> tuple[FinalPromptConstraintEvidence, ...]:
    """Append verified parser evidence and deterministically supersede prior active constraints."""

    parsed = ParsedCandidateEnrichmentResult.model_validate(enrichment)
    source = MessageSource.model_validate(source)
    revision = validate_design_revision(authoritative_revision)
    if source != parsed.parser_proposal.source:
        raise ValueError("constraint evidence source does not match parser provenance")
    retained = [FinalPromptConstraintEvidence.model_validate(item) for item in previous]
    if any(
        item.session_id != session_id or item.organization_id != organization_id
        for item in retained
    ):
        raise ValueError("constraint evidence belongs to another session scope")

    additions = []
    for candidate in parsed.parse_result.candidates:
        if candidate.classification not in {
            CandidateClassification.REQUIREMENT,
            CandidateClassification.PROHIBITION,
            CandidateClassification.PRESERVATION,
        }:
            continue
        context_span = None
        if (
            candidate.semantic_subject is None
            and candidate.classification == CandidateClassification.REQUIREMENT
        ):
            disposition = next(d for d in parsed.dispositions if d.candidate == candidate)
            if (
                candidate.certainty == CandidateCertainty.AMBIGUOUS
                and candidate.target in _TARGET_QUESTION
            ):
                continue  # The existing answer/plan lineage owns this ambiguity.
            if any(
                d.candidate.evidence == candidate.evidence
                and (
                    (
                        d.candidate.normalized_values == candidate.normalized_values
                        and (
                            d.candidate.subject == candidate.subject
                            or d.candidate.semantic_subject is not None
                        )
                    )
                    or (
                        candidate.target is not None
                        and d.candidate.target == candidate.target
                        and d.candidate.subject == candidate.subject
                    )
                )
                and d.outcome
                in {
                    CandidateDispositionOutcome.APPLIED,
                    CandidateDispositionOutcome.KEPT,
                    CandidateDispositionOutcome.NO_CHANGE,
                }
                for d in parsed.dispositions
            ):
                continue  # The same sourced intent already has its approved binding.
            # Recognition is not acceptance. Preserve unsupported user wording
            # with its original Message/span through the existing unresolved DTO.
            # Accepted Dictionary facts keep their canonical provenance instead.
            if disposition.outcome != CandidateDispositionOutcome.DEFERRED:
                continue
            if candidate.subject.value == "unknown" and not candidate.normalized_values:
                continue
            left, right, _ = _ownership_context(
                parsed.parse_result.original_text, candidate.evidence.start, candidate.evidence.end
            )
            # Cite the source phrase, so "gold prongs" is not presented as an
            # unresolved global "gold" fact. This is quotation, never binding.
            text = parsed.parse_result.original_text
            while left < right and text[left].isspace():
                left += 1
            while right > left and text[right - 1].isspace():
                right -= 1
            context_span = (left, right)
        explicit = (
            candidate.certainty == CandidateCertainty.EXPLICIT
            and candidate.semantic_subject is not None
        )
        canonical_requirement = False
        if candidate.semantic_subject == "composition.symmetry_mode":
            # A rejected/locked conflicting request cannot become an active
            # preservation instruction contradicting the canonical design.
            composition = getattr(revision.design, "composition", None)
            symmetry = getattr(getattr(composition, "value", None), "symmetry_mode", None)
            explicit = explicit and getattr(symmetry, "value", None) == "asymmetrical"
            if candidate.classification == CandidateClassification.REQUIREMENT:
                canonical_requirement = explicit and any(
                    disposition.candidate == candidate
                    and disposition.outcome
                    in {
                        CandidateDispositionOutcome.APPLIED,
                        CandidateDispositionOutcome.KEPT,
                        CandidateDispositionOutcome.NO_CHANGE,
                    }
                    for disposition in parsed.dispositions
                )
                # Only this exact accepted candidate and matching canonical value
                # can be described as fulfilled. Other unresolved intent is kept.
                explicit = canonical_requirement
        span_start, span_end = context_span or (candidate.evidence.start, candidate.evidence.end)
        wording = parsed.parse_result.original_text[span_start:span_end]
        kind = candidate.classification.value
        identity = {
            "session_id": str(session_id),
            "organization_id": str(organization_id),
            "message_id": source.message_id,
            "candidate_id": candidate.candidate_id,
            "span_start": span_start,
            "span_end": span_end,
            "kind": kind,
            "semantic_subject": candidate.semantic_subject,
        }
        evidence_id = f"constraint_{_hash(identity)[:24]}"
        payload = {
            "schema_version": "1.0.0",
            "evidence_id": evidence_id,
            "session_id": session_id,
            "organization_id": organization_id,
            "kind": kind,
            "status": "active" if explicit else "unresolved",
            "acceptance": "user_explicit" if explicit else "unresolved",
            "semantic_subject": candidate.semantic_subject,
            "canonical_target": candidate.semantic_subject if canonical_requirement else None,
            "normalized_instruction": (
                _INSTRUCTIONS.get(
                    (candidate.semantic_subject, kind, parsed.parse_result.requested_locale)
                )
                if explicit
                else None
            ),
            "original_wording": wording,
            "source": source,
            "source_candidate_id": candidate.candidate_id,
            "source_span_start": span_start,
            "source_span_end": span_end,
            "source_revision_id": revision.revision_id,
            "source_enrichment_cycle_id": enrichment_cycle_id,
            "superseded_by_evidence_id": None,
        }
        if explicit and payload["normalized_instruction"] is None:
            payload["status"] = "unresolved"
            payload["acceptance"] = "unresolved"
        additions.append(_evidence(payload))

    # The approved KEEP strengthens the same fulfilled canonical requirement.
    # Retain both original spans/IDs; the current preservation instruction owns
    # the active slot, with normal explicit supersession lineage to the fact.
    preservation = next(
        (
            item
            for item in additions
            if item.status == "active"
            and item.kind == "preservation"
            and item.semantic_subject == "composition.symmetry_mode"
        ),
        None,
    )
    if preservation is not None:
        additions = [
            _supersede(item, preservation.evidence_id)
            if item.status == "active"
            and item.kind == "requirement"
            and item.canonical_target == preservation.semantic_subject
            else item
            for item in additions
        ]

    for index, addition in enumerate(additions):
        if addition.status != "active":
            continue
        # Reaffirmation is not revocation. Compare the original preserved fact
        # with current canonical state, not wording, locale or matrix outcome
        # alone. This grants neither cancellation authority nor an intrinsic lock.
        covering = next(
            (
                item
                for item in retained
                if item.status == "active"
                and item.kind == "preservation"
                and _same_preserved_fact(item, addition, revision, load_source_revision)
            ),
            None,
        )
        if covering is not None:
            additions[index] = _supersede(addition, covering.evidence_id)
            continue
        retained = [
            _supersede(item, addition.evidence_id)
            if item.status == "active" and item.semantic_subject == addition.semantic_subject
            else item
            for item in retained
        ]
    by_id = {item.evidence_id: item for item in (*retained, *additions)}
    return tuple(by_id[key] for key in sorted(by_id))


def _same_preserved_fact(keeper, requirement, revision, load_source_revision):
    target = requirement.canonical_target
    if requirement.kind != "requirement" or target is None or target != keeper.semantic_subject:
        return False
    if keeper.source_revision_id == revision.revision_id:
        original = revision
    else:
        if load_source_revision is None:
            raise ConstraintEvidenceIntegrityError(
                "canonical preservation requires its source revision"
            )
        # Trusted callers must use the existing organization/session-scoped read.
        original = validate_design_revision(load_source_revision(keeper.source_revision_id))
        if (
            original.revision_id != keeper.source_revision_id
            or original.design_id != revision.design_id
        ):
            raise ConstraintEvidenceIntegrityError(
                "canonical preservation source revision mismatch"
            )
    previous = {e.concrete_target: e for e in project_revision(original).specification_entries}.get(
        target
    )
    current = {e.concrete_target: e for e in project_revision(revision).specification_entries}.get(
        target
    )
    return (
        previous is not None
        and current is not None
        and previous.applicability == current.applicability == "value"
        and previous.value == current.value
    )


def _supersede(item: FinalPromptConstraintEvidence, replacement_id: str):
    payload = item.model_dump(mode="json", exclude={"content_hash"})
    payload["status"] = "superseded"
    payload["superseded_by_evidence_id"] = replacement_id
    return _evidence(payload)


def _evidence(payload):
    canonical = _json(payload)
    return FinalPromptConstraintEvidence(**payload, content_hash=_hash(canonical))


def _json(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    return value


def _hash(payload) -> str:
    canonical = json.dumps(
        _json(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
