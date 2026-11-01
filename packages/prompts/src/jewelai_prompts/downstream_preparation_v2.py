"""Exact F04 source3/gate2/render2/preparation2 boundary; no provider execution."""

import hashlib
from dataclasses import dataclass
from datetime import UTC
from typing import Literal

from jewelai_domain.clarification_state import (
    Sha256,
    StrictEvidenceModel,
    validate_availability_overlay,
)
from jewelai_domain.rules_v2 import RuleDecisionV2
from pydantic import ValidationError, model_validator

from .downstream_preparation import (
    ARTIFACT_MAX_BYTES,
    SOURCE_MAX_BYTES,
    GenerationPreparation,
    GenerationPreparationError,
    GenerationPreparationPayload,
    PreparationErrorCode,
    PreparationGateEvidence,
    SemanticCoverage,
    SemanticRendering,
    _alias,
    _aliases,
    _check_source,
    _render_semantic_sections,
    _strict_json,
    _validate_preparation_payload,
    canonical_bytes,
    preparation_hash,
)
from .final_prompt_v3 import CanonicalInternalFinalPromptHandoffV3


class PreparationGateEvidenceV2(PreparationGateEvidence, StrictEvidenceModel):
    schema_version: Literal["2.0.0"]
    contract_profile: Literal["jewelai.prompt-enrichment.f04/2.0.0"]
    availability_overlay_hash: Sha256
    effective_unresolved_frontier_hash: Sha256
    rule_decision: RuleDecisionV2

    @model_validator(mode="after")
    def validate_f04_gate(self):
        if self.rule_decision.rules_artifact_version != "2.0.0":
            raise ValueError("Gate2 requires Rules2")
        return self


class SemanticCoverageV2(SemanticCoverage, StrictEvidenceModel):
    rendered_section: Literal[
        "facts", "constraints", "references", "disclosures", "unresolved", "availability"
    ]


class SemanticRenderingV2(SemanticRendering, StrictEvidenceModel):
    schema_version: Literal["2.0.0"]
    renderer_version: Literal["2.0.0"]
    semantic_coverage: tuple[SemanticCoverageV2, ...]


def render_semantic_source_v2(source, gate):
    source = CanonicalInternalFinalPromptHandoffV3.model_validate_json(canonical_bytes(source))
    gate = PreparationGateEvidenceV2.model_validate_json(canonical_bytes(gate))
    prompt = source.internal_final_prompt
    frontier = prompt.effective_unresolved_frontier
    core = frontier.frontier_core
    try:
        validate_availability_overlay(prompt.availability_overlay, gate.revision, scope=core.scope)
    except ValueError:
        raise GenerationPreparationError(PreparationErrorCode.INVALID_GATE) from None
    if (
        gate.availability_overlay_hash != prompt.availability_overlay.content_hash
        or gate.effective_unresolved_frontier_hash != frontier.content_hash
        or frontier.current_plan_ref.plan_id != gate.clarification_plan_id
        or frontier.current_plan_ref.content_hash != gate.clarification_plan_hash
        or gate.blocking_clarification_ids
        != tuple(
            sorted(
                ref.question_id
                for ref in frontier.origin_question_refs
                if any(s.cause_id == ref.cause_id and s.blocks_current for s in core.cause_states)
            )
        )
        or gate.rule_decision.blocking_cause_ids
        != tuple(sorted(s.cause_id for s in core.cause_states if s.blocks_current))
    ):
        raise GenerationPreparationError(PreparationErrorCode.INVALID_GATE)
    _check_source(source, gate, _validated_f04=True)
    aliases = _aliases(gate.revision)

    def extras(section, lines, coverage):
        availability = []
        for i, entry in enumerate(prompt.availability_overlay.entries):
            text = (
                f"AVAILABILITY {_alias(entry.target.concrete_target, aliases)} "
                f"= {entry.availability}"
            )
            if entry.unknown_requirement is not None:
                text += f"; unknown_requirement={entry.unknown_requirement}"
            if entry.not_applicable is not None:
                text += "; reason=" + canonical_bytes(entry.not_applicable.reason).decode()
            text += (
                f"; confirmed={str(entry.confirmed).lower()}; locked={str(entry.locked).lower()}"
            )
            availability.append((f"/internal_final_prompt/availability_overlay/entries/{i}", text))
        section("availability", availability)
        # Unbound requests remain explicitly unaccepted source evidence, not new
        # invented canonical targets or professional criticality rules.
        section(
            "disclosures",
            [
                (
                    f"/internal_final_prompt/constraint_evidence/{i}",
                    "UNRESOLVED USER REQUEST (not an accepted canonical requirement): "
                    + canonical_bytes(e.original_wording).decode(),
                )
                for i, e in enumerate(prompt.constraint_evidence)
                if e.status == "unresolved"
            ],
        )
        by_cause = {u.cause_id: i for i, u in enumerate(prompt.unresolved_details)}
        by_pointer = {c.source_pointer: c.rendered_ordinal for c in coverage}
        for index, state in enumerate(core.cause_states):
            if state.status != "OPEN":
                continue
            ordinal = by_pointer[
                f"/internal_final_prompt/unresolved_details/{by_cause[state.cause_id]}"
            ]
            coverage.append(
                SemanticCoverageV2(
                    source_pointer=f"/internal_final_prompt/effective_unresolved_frontier/frontier_core/cause_states/{index}",
                    rendered_section="unresolved",
                    rendered_ordinal=ordinal,
                )
            )

    return _render_semantic_sections(
        source,
        gate,
        version="2.0.0",
        model_type=SemanticRenderingV2,
        coverage_type=SemanticCoverageV2,
        extra_sections=extras,
        unresolved_formatter=lambda u, a: (
            f"{_alias(u.target, a)}: {u.classification}; kind={u.kind}; "
            f"criticality={u.criticality}; not an accepted requirement"
        ),
    )


class GenerationPreparationPayloadV2(GenerationPreparationPayload, StrictEvidenceModel):
    schema_version: Literal["2.0.0"]
    source_handoff: CanonicalInternalFinalPromptHandoffV3
    gate_evidence: PreparationGateEvidenceV2
    execution: SemanticRenderingV2

    @model_validator(mode="after")
    def validate_preparation(self):
        return _validate_preparation_payload(
            self, version="2.0.0", renderer=render_semantic_source_v2
        )


@dataclass(frozen=True, slots=True)
class GenerationPreparationV2(GenerationPreparation):
    def __post_init__(self):
        if not isinstance(self.canonical, bytes) or len(self.canonical) > ARTIFACT_MAX_BYTES:
            raise GenerationPreparationError(PreparationErrorCode.CAPACITY)
        payload = _strict_json(self.canonical)
        if payload.get("schema_version") != "2.0.0":
            raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_VERSION)
        try:
            checked = GenerationPreparationPayloadV2.model_validate_json(canonical_bytes(payload))
        except ValidationError:
            raise GenerationPreparationError(PreparationErrorCode.INTEGRITY) from None
        if canonical_bytes(checked) != self.canonical:
            raise GenerationPreparationError(PreparationErrorCode.INTEGRITY)

    @property
    def payload(self):
        return GenerationPreparationPayloadV2.model_validate_json(self.canonical)


def build_generation_preparation_v2(source, gate, *, preparation_id, created_at):
    original_source = canonical_bytes(source)
    original_gate = canonical_bytes(gate)
    source = CanonicalInternalFinalPromptHandoffV3.model_validate_json(original_source)
    gate = PreparationGateEvidenceV2.model_validate_json(original_gate)
    if canonical_bytes(source) != original_source or canonical_bytes(gate) != original_gate:
        raise GenerationPreparationError(PreparationErrorCode.INTEGRITY)
    if len(original_source) + len(original_gate) > SOURCE_MAX_BYTES:
        raise GenerationPreparationError(PreparationErrorCode.CAPACITY)
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise GenerationPreparationError(PreparationErrorCode.INVALID_SOURCE)
    payload = dict(
        schema_version="2.0.0",
        preparation_id=str(preparation_id),
        created_at=created_at.astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        **{
            key: source.internal_final_prompt.model_dump(mode="json")[key]
            for key in (
                "organization_id",
                "session_id",
                "design_id",
                "product_state_revision_id",
                "enrichment_cycle_id",
                "enrichment_cycle_number",
            )
        },
        enrichment_result_hash=source.internal_final_prompt.enrichment_result_content_hash,
        source_handoff=source.model_dump(mode="json"),
        gate_evidence=gate.model_dump(mode="json"),
        source_handoff_hash=source.content_hash,
        source_bytes_sha256=hashlib.sha256(original_source).hexdigest(),
        gate_evidence_hash=preparation_hash("jewelai.preparation.gate/2.0.0", gate),
        execution=render_semantic_source_v2(source, gate).model_dump(mode="json"),
    )
    payload["artifact_hash"] = preparation_hash("jewelai.preparation.artifact/2.0.0", payload)
    return GenerationPreparationV2(canonical_bytes(payload))


def decode_generation_preparation(value):
    raw = value.canonical if isinstance(value, GenerationPreparation) else value
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    payload = _strict_json(raw)
    if payload.get("schema_version") == "2.0.0":
        return GenerationPreparationV2(raw)
    return GenerationPreparation(raw)
