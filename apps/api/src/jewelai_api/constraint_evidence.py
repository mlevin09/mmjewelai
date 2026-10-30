"""Deterministic preservation of explicit non-schema constraint evidence."""

import hashlib
import json
from uuid import UUID

from jewelai_domain.models import MessageSource
from jewelai_domain.models_v1_1 import AnyDesignRevision, validate_design_revision
from jewelai_parser import (
    CandidateCertainty,
    CandidateClassification,
)
from jewelai_prompts import FinalPromptConstraintEvidence

from .parsed_enrichment import CandidateDispositionOutcome, ParsedCandidateEnrichmentResult

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
        if candidate.semantic_subject is None and candidate.classification not in {
            CandidateClassification.PROHIBITION,
            CandidateClassification.PRESERVATION,
        }:
            continue
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
        kind = candidate.classification.value
        identity = {
            "session_id": str(session_id),
            "organization_id": str(organization_id),
            "message_id": source.message_id,
            "candidate_id": candidate.candidate_id,
            "span_start": candidate.evidence.start,
            "span_end": candidate.evidence.end,
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
            "original_wording": candidate.evidence.text,
            "source": source,
            "source_candidate_id": candidate.candidate_id,
            "source_span_start": candidate.evidence.start,
            "source_span_end": candidate.evidence.end,
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

    for addition in additions:
        if addition.status != "active":
            continue
        retained = [
            _supersede(item, addition.evidence_id)
            if item.status == "active" and item.semantic_subject == addition.semantic_subject
            else item
            for item in retained
        ]
    by_id = {item.evidence_id: item for item in (*retained, *additions)}
    return tuple(by_id[key] for key in sorted(by_id))


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
