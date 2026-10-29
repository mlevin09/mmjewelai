"""Pure canonical preparation and exact-version IFP readers; no provider or storage calls.

Current IFP/handoff writers select 2.1; retained 2.0 sources keep their original validation.
The preparation owns canonical bytes; mutable JSON views are always defensive copies.
"""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from jewelai_domain.knowledge_policy import (
    PreservationIntent,
    RuntimeProvenance,
    RuntimeSemanticState,
)
from jewelai_domain.models import ImmutableModel
from jewelai_domain.models_v1_1 import AnyDesignRevision
from jewelai_domain.rules import ReadyDecision, RuleDecision
from pydantic import (
    AwareDatetime,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)

from .enrichment import ParametricEnrichmentReference, parametric_reference_context_is_eligible
from .final_prompt import (
    FinalPromptAssembly,
    InternalFinalPrompt,
    KnowledgeReleaseReference,
    UserReadableJewelryDescription,
    _render_internal_prompt,
)
from .handoff import InternalFinalPromptHandoff
from .models import PromptDisclosure, Sha256
from .revision_projection import project_revision

# Provisional engineering bounds, NOT Schema v1.1 production qualification (#118).
SOURCE_MAX_BYTES = 1_048_576
ARTIFACT_MAX_BYTES = 2_097_152
RENDER_MAX_CHARACTERS = 20_000
RENDER_MAX_BYTES = 80_000
# IFP-only successor capacity; not the description or execution-rendering policy.
IFP_V2_1_MAX_CHARACTERS = 32_000
IFP_V2_1_MAX_BYTES = 128_000
RENDERER_ID = "jewelai.semantic-text"
RENDERER_VERSION = "1.0.0"


class PreparationErrorCode(StrEnum):
    INVALID_SOURCE = "invalid_preparation_source"
    INVALID_GATE = "invalid_preparation_gate"
    NOT_READY = "final_output_not_ready"
    UNSUPPORTED_VERSION = "unsupported_contract_version"
    UNSUPPORTED_SEMANTICS = "unsupported_source_semantics"
    INTEGRITY = "preparation_integrity_mismatch"
    CAPACITY = "preparation_capacity_exceeded"


class GenerationPreparationError(ValueError):
    """Bounded safe error; never include supplied source or validation/exception payloads."""

    def __init__(self, code: PreparationErrorCode):
        self.code = code
        super().__init__(code.value)


def canonical_bytes(value: object) -> bytes:
    """Pinned compact Python JSON; preserve exact Unicode and numeric spelling, reject NaN."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise GenerationPreparationError(PreparationErrorCode.INVALID_SOURCE) from None


def preparation_hash(domain: str, value: object) -> str:
    return hashlib.sha256(domain.encode("ascii") + b"\0" + canonical_bytes(value)).hexdigest()


def source_content_hash(value: object) -> str:
    """Existing source hash algorithm; never reinterpret a frozen v1 hash under a new tag."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _same_value(left, right) -> bool:
    # Python equality conflates 1/1.0 and False/0; canonical source numbers are exact.
    return canonical_bytes(left) == canonical_bytes(right)


def _strict_json(value: bytes | str) -> dict:
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = item
        return result

    def invalid_constant(_):
        raise ValueError("nonfinite number")

    try:
        result = json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_constant)
        if not isinstance(result, dict):
            raise ValueError("not an object")
        canonical_bytes(result)
        return result
    except (ValueError, TypeError, UnicodeError):
        raise GenerationPreparationError(PreparationErrorCode.INTEGRITY) from None


class CanonicalInternalFinalPrompt(InternalFinalPrompt):
    """Staged v2 source; full authority/evidence retained, no live assembly switch."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    description: UserReadableJewelryDescription
    parametric_references: tuple[ParametricEnrichmentReference, ...]
    disclosures: tuple[PromptDisclosure, ...]

    @model_validator(mode="after")
    def validate_structured_text(self):
        for value in (self.knowledge_release.package_id, self.knowledge_release.artifact_version):
            if not value or value != value.strip():
                raise GenerationPreparationError(PreparationErrorCode.INVALID_SOURCE)
        if (
            self.description.content_hash != self.description_content_hash
            or self.description.authoritative_revision_id != self.product_state_revision_id
            or self.description.locale != self.locale
        ):
            raise GenerationPreparationError(PreparationErrorCode.INVALID_SOURCE)
        expected = render_canonical_source_text(self)
        if self.prompt_text != expected:
            raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
        return self


def render_canonical_source_text(prompt: CanonicalInternalFinalPrompt) -> str:
    """Reuse existing internal structured formatter, changing only its version heading."""
    text = _render_internal_prompt(
        prompt.description,
        prompt.design_facts,
        prompt.constraints,
        prompt.unresolved_details,
        prompt.readiness,
        prompt.parametric_references,
    )
    _, body = text.split("\n", 1)
    return f"JEWELAI INTERNAL FINAL PROMPT {prompt.schema_version}\n" + body


class CanonicalFinalPromptAssembly(FinalPromptAssembly):
    internal_final_prompt: CanonicalInternalFinalPrompt


class CanonicalInternalFinalPromptHandoff(InternalFinalPromptHandoff):
    schema_version: Literal["2.0.0"] = "2.0.0"
    internal_final_prompt_schema_version: Literal["2.0.0"] = "2.0.0"
    internal_final_prompt: CanonicalInternalFinalPrompt


def check_ifp_v2_1_capacity(text: str) -> None:
    if len(text) > IFP_V2_1_MAX_CHARACTERS or len(text.encode("utf-8")) > IFP_V2_1_MAX_BYTES:
        raise GenerationPreparationError(PreparationErrorCode.CAPACITY)


class CanonicalInternalFinalPromptV2_1(CanonicalInternalFinalPrompt):
    """IFP-only capacity successor. The original 2.0 reader remains frozen."""

    schema_version: Literal["2.1.0"] = "2.1.0"
    prompt_text: Annotated[str, StringConstraints(min_length=1, max_length=32_000, pattern=r"\S")]

    @field_validator("prompt_text", mode="before")
    @classmethod
    def validate_capacity(cls, value):
        if isinstance(value, str):
            check_ifp_v2_1_capacity(value)
        return value


class CanonicalFinalPromptAssemblyV2_1(CanonicalFinalPromptAssembly):
    internal_final_prompt: CanonicalInternalFinalPromptV2_1


class CanonicalInternalFinalPromptHandoffV2_1(CanonicalInternalFinalPromptHandoff):
    schema_version: Literal["2.1.0"] = "2.1.0"
    internal_final_prompt_schema_version: Literal["2.1.0"] = "2.1.0"
    internal_final_prompt: Annotated[
        CanonicalInternalFinalPromptV2_1, Field(discriminator="schema_version")
    ]


AnyCanonicalInternalFinalPrompt = Annotated[
    CanonicalInternalFinalPrompt | CanonicalInternalFinalPromptV2_1,
    Field(discriminator="schema_version"),
]
AnyCanonicalInternalFinalPromptHandoff = Annotated[
    CanonicalInternalFinalPromptHandoff | CanonicalInternalFinalPromptHandoffV2_1,
    Field(discriminator="schema_version"),
]
_IFP_DECODER = TypeAdapter(AnyCanonicalInternalFinalPrompt)
_HANDOFF_DECODER = TypeAdapter(AnyCanonicalInternalFinalPromptHandoff)


def _explicit_canonical_version(value: object) -> str:
    """Check wire input before Pydantic can fill frozen-model version defaults."""
    if not isinstance(value, Mapping):
        raise GenerationPreparationError(PreparationErrorCode.INVALID_SOURCE)
    version = value.get("schema_version")
    if not isinstance(version, str) or version not in ("2.0.0", "2.1.0"):
        raise GenerationPreparationError(PreparationErrorCode.INVALID_SOURCE)
    return version


def decode_canonical_internal_final_prompt(value: object) -> AnyCanonicalInternalFinalPrompt:
    if isinstance(value, (bytes, str)):
        value = _strict_json(value)
    elif hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    _explicit_canonical_version(value)
    return _IFP_DECODER.validate_python(value)


def decode_canonical_handoff(value: object) -> AnyCanonicalInternalFinalPromptHandoff:
    if isinstance(value, (bytes, str)):
        value = _strict_json(value)
    elif hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    version = _explicit_canonical_version(value)
    if (
        value.get("internal_final_prompt_schema_version") != version
        or _explicit_canonical_version(value.get("internal_final_prompt")) != version
    ):
        raise GenerationPreparationError(PreparationErrorCode.INVALID_SOURCE)
    return _HANDOFF_DECODER.validate_python(value)


class DecisionReference(ImmutableModel):
    record_id: UUID
    content_hash: Sha256


class DecisionFrontier(ImmutableModel):
    answers: tuple[DecisionReference, ...]
    corrections: tuple[DecisionReference, ...]

    @model_validator(mode="after")
    def validate_order(self):
        for items in (self.answers, self.corrections):
            keys = [str(item.record_id) for item in items]
            if keys != sorted(set(keys)):
                raise GenerationPreparationError(PreparationErrorCode.INVALID_GATE)
        return self


class PreparationGateEvidence(ImmutableModel):
    """Caller-supplied evidence, not authorization or proof of a transaction/ACTIVE lookup."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    organization_id: UUID
    session_id: UUID
    revision: AnyDesignRevision
    enrichment_cycle_id: UUID
    enrichment_cycle_number: Annotated[StrictInt, Field(ge=1)]
    enrichment_result_hash: Sha256
    source_handoff_hash: Sha256
    knowledge_release: KnowledgeReleaseReference
    rule_decision: RuleDecision
    workflow_status: Literal[
        "enrichment_completed",
        "clarification_available",
        "blocking_clarification_unresolved",
        "clarification_answer_recorded",
        "correction_applied",
        "correction_deferred",
        "final_output_ready",
        "final_output_ready_with_unresolved",
        "final_output_blocked",
    ]
    clarification_plan_id: UUID
    clarification_plan_hash: Sha256
    blocking_clarification_ids: tuple[str, ...]
    decision_frontier: DecisionFrontier
    decision_frontier_hash: Sha256
    release_verified: StrictBool

    @model_validator(mode="after")
    def validate_frontier(self):
        expected = preparation_hash("jewelai.preparation.frontier/1.0.0", self.decision_frontier)
        if self.decision_frontier_hash != expected:
            raise GenerationPreparationError(PreparationErrorCode.INVALID_GATE)
        if list(self.blocking_clarification_ids) != sorted(set(self.blocking_clarification_ids)):
            raise GenerationPreparationError(PreparationErrorCode.INVALID_GATE)
        return self


class SemanticCoverage(ImmutableModel):
    source_pointer: str
    rendered_section: Literal["facts", "constraints", "references", "disclosures", "unresolved"]
    rendered_ordinal: Annotated[StrictInt, Field(ge=1)]


class SemanticRendering(ImmutableModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    renderer_id: Literal["jewelai.semantic-text"] = RENDERER_ID
    renderer_version: Literal["1.0.0"] = RENDERER_VERSION
    rendering_text: str
    rendering_characters: Annotated[StrictInt, Field(ge=1)]
    rendering_utf8_bytes: Annotated[StrictInt, Field(ge=1)]
    rendering_hash: Sha256
    semantic_coverage: tuple[SemanticCoverage, ...]


def _check_source(source: CanonicalInternalFinalPromptHandoff, gate: PreparationGateEvidence):
    prompt = source.internal_final_prompt
    revision = gate.revision
    for item in (*prompt.design_facts, *prompt.constraints, *prompt.unresolved_details):
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", item.target):
            raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
    if (
        source.organization_id != gate.organization_id
        or source.session_id != gate.session_id
        or source.product_state_revision_id != revision.revision_id
        or prompt.design_id != revision.design_id
        or source.enrichment_cycle_id != gate.enrichment_cycle_id
        or prompt.enrichment_cycle_number != gate.enrichment_cycle_number
        or prompt.enrichment_result_content_hash != gate.enrichment_result_hash
        or source.content_hash != gate.source_handoff_hash
        or source.knowledge_release != gate.knowledge_release
        or prompt.artifact_versions.design_schema_version != revision.schema_version
        or prompt.artifact_versions.rules_artifact_version
        != gate.rule_decision.rules_artifact_version
    ):
        raise GenerationPreparationError(PreparationErrorCode.INVALID_GATE)
    if (
        not source.ready_for_downstream_preparation
        or not gate.release_verified
        or not isinstance(gate.rule_decision, ReadyDecision)
        or gate.blocking_clarification_ids
        or gate.workflow_status in {"blocking_clarification_unresolved", "final_output_blocked"}
        or any(item.blocking for item in prompt.unresolved_details)
        or any(item.blocks_progression for item in prompt.decision_lineage)
    ):
        raise GenerationPreparationError(PreparationErrorCode.NOT_READY)
    if gate.workflow_status in {"final_output_ready", "final_output_ready_with_unresolved"} and (
        gate.workflow_status != "final_output_" + source.readiness.value
    ):
        raise GenerationPreparationError(PreparationErrorCode.INVALID_GATE)
    projection = project_revision(revision)
    entries = {item.concrete_target: item for item in projection.specification_entries}
    facts = {item.target: item for item in prompt.design_facts}
    if len(facts) != len(prompt.design_facts) or facts.keys() != entries.keys():
        raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
    for target, entry in entries.items():
        fact = facts[target]
        if not _same_value(fact.value, entry.value) or any(
            getattr(fact, key) != getattr(entry, key)
            for key in ("applicability", "origin", "confirmed", "locked")
        ):
            raise GenerationPreparationError(PreparationErrorCode.INTEGRITY)
        if fact.semantic_state in {
            RuntimeSemanticState.RECOMMENDED,
            RuntimeSemanticState.AMBIGUOUS,
            RuntimeSemanticState.MISSING,
        } or (
            fact.semantic_state == RuntimeSemanticState.ACCEPTED
            and fact.provenance != RuntimeProvenance.USER_ACCEPTED_RECOMMENDATION
        ):
            raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
    if prompt.disclosures != projection.disclosures:
        raise GenerationPreparationError(PreparationErrorCode.INTEGRITY)
    reference_keys = [canonical_bytes(item) for item in prompt.parametric_references]
    if len(reference_keys) != len(set(reference_keys)) or (
        reference_keys and not parametric_reference_context_is_eligible(revision)
    ):
        raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
    for ref in prompt.parametric_references:
        stone = revision.design.center_stone
        if (
            ref.material_id != stone.material.value
            or ref.shape_id != stone.shape.value
            or ref.weight_ct != stone.weight.value.value
        ):
            raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
    for item in prompt.enrichment_evidence:
        fact = facts.get(item.target)
        accepted = fact is not None and (
            fact.semantic_state == RuntimeSemanticState.ACCEPTED
            and fact.provenance == RuntimeProvenance.USER_ACCEPTED_RECOMMENDATION
        )
        if item.accepted_as_requirement != accepted:
            raise GenerationPreparationError(PreparationErrorCode.INTEGRITY)
        if (
            fact is not None
            and item.preservation
            in {
                PreservationIntent.KEEP,
                PreservationIntent.LOCKED,
            }
            and not any(
                c.kind == "preservation"
                and c.target == fact.target
                and _same_value(c.value, fact.value)
                for c in prompt.constraints
            )
        ):
            raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
    unresolved_keys = [canonical_bytes(item) for item in prompt.unresolved_details]
    if len(unresolved_keys) != len(set(unresolved_keys)):
        raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
    lineage_keys = [(item.kind, item.decision_id) for item in prompt.decision_lineage]
    if len(lineage_keys) != len(set(lineage_keys)):
        raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
    for item in prompt.decision_lineage:
        if (
            item.session_id != source.session_id
            or item.applies_to_revision_id != revision.revision_id
            or item.knowledge_package_id != source.knowledge_release.package_id
            or item.knowledge_artifact_version != source.knowledge_release.artifact_version
            or item.knowledge_runtime_sha256 != source.knowledge_release.runtime_sha256
            or item.knowledge_validation_report_sha256
            != source.knowledge_release.validation_report_sha256
        ):
            raise GenerationPreparationError(PreparationErrorCode.INVALID_SOURCE)
    evidence = {item.evidence_id: item for item in prompt.constraint_evidence}
    if len(evidence) != len(prompt.constraint_evidence):
        raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
    active = []
    subjects = set()
    for item in evidence.values():
        if item.organization_id != source.organization_id or item.session_id != source.session_id:
            raise GenerationPreparationError(PreparationErrorCode.INVALID_SOURCE)
        if item.status == "superseded":
            seen = {item.evidence_id}
            replacement = item
            while replacement.status == "superseded":
                key = replacement.superseded_by_evidence_id
                if key in seen or key not in evidence:
                    raise GenerationPreparationError(PreparationErrorCode.INVALID_SOURCE)
                seen.add(key)
                replacement = evidence[key]
                if replacement.semantic_subject != item.semantic_subject:
                    raise GenerationPreparationError(PreparationErrorCode.INVALID_SOURCE)
        if item.status == "active":
            if item.semantic_subject in subjects:
                raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
            subjects.add(item.semantic_subject)
            active.append(
                (
                    item.kind,
                    item.canonical_target or item.semantic_subject,
                    item.normalized_instruction,
                )
            )
        if item.status == "unresolved" and not any(
            u.target == (item.semantic_subject or "constraint.unresolved")
            and u.classification == "ambiguous"
            and item.evidence_id in u.source_ids
            for u in prompt.unresolved_details
        ):
            raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
    constraints = [(c.kind, c.target, c.instruction) for c in prompt.constraints]
    if len(constraints) != len(set(constraints)):
        raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
    for key in active:
        if key not in constraints:
            raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
    for fact in facts.values():
        required_kind = "prohibition" if fact.applicability == "not_applicable" else "requirement"
        if not any(
            c.target == fact.target and c.kind == required_kind and _same_value(c.value, fact.value)
            for c in prompt.constraints
        ):
            raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
        if fact.locked and not any(
            c.kind == "preservation"
            and c.target == fact.target
            and _same_value(c.value, fact.value)
            for c in prompt.constraints
        ):
            raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
    for c in prompt.constraints:
        if (c.kind, c.target, c.instruction) in active:
            if c.value is not None:
                raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
            continue
        fact = facts.get(c.target)
        if fact is None or not _same_value(c.value, fact.value):
            raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
        if c.kind == "requirement" and (
            fact.applicability != "value"
            or c.instruction != "Preserve this authoritative design value."
        ):
            raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
        if c.kind == "prohibition":
            disclosure = next(
                (d for d in projection.disclosures if d.concrete_target == c.target), None
            )
            instruction = (disclosure.reason if disclosure else None) or (
                "Do not include this explicitly inapplicable design element."
            )
            if fact.applicability != "not_applicable" or c.instruction != instruction:
                raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
        if c.kind == "preservation" and c.instruction != (
            "This confirmed locked value must not change."
            if fact.locked
            else "Keep the existing authoritative design value unchanged."
        ):
            raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
        if c.kind == "preservation" and not (
            fact.locked
            or any(
                e.target == fact.target
                and e.preservation in {PreservationIntent.KEEP, PreservationIntent.LOCKED}
                for e in prompt.enrichment_evidence
            )
        ):
            raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)


def _aliases(revision) -> dict[str, str]:
    aliases = {}
    for prefix, items, key, label in (
        ("side_stones", revision.design.side_stones, "group_id", "side_group"),
        (
            "metal.components",
            getattr(getattr(revision.design.metal, "components", None), "value", ()) or (),
            "component_id",
            "component",
        ),
        (
            "decorative_elements",
            getattr(getattr(revision.design, "decorative_elements", None), "value", ()) or (),
            "element_id",
            "element",
        ),
    ):
        for number, item in enumerate(sorted(items, key=lambda x: getattr(x, key)), 1):
            aliases[f"{prefix}.{getattr(item, key)}"] = f"{prefix}.{label}_{number}"
    return aliases


def _alias(target: str, aliases: dict[str, str]) -> str:
    for prefix in sorted(aliases, key=lambda x: (-len(x), x)):
        if target == prefix or target.startswith(prefix + "."):
            return aliases[prefix] + target[len(prefix) :]
    return target


def _safe_value(value, aliases, target):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in {"source", "sources"} and value.get("availability") in {
                "value",
                "not_applicable",
                "unknown",
            }:
                # A validated nested state wrapper: provenance stays in the source artifact.
                continue
            if key in {
                "source",
                "sources",
                "message_id",
                "asset_id",
                "organization_id",
                "session_id",
            }:
                raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
            if key in {"component_id", "element_id", "group_id"}:
                prefix = {
                    "component_id": "metal.components",
                    "element_id": "decorative_elements",
                    "group_id": "side_stones",
                }[key]
                alias = aliases.get(f"{prefix}.{item}")
                if alias is None:
                    raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
                result[key] = alias.rsplit(".", 1)[1]
            else:
                result[key] = _safe_value(item, aliases, target)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, aliases, target) for item in value]
    return value


def render_semantic_source(
    source: AnyCanonicalInternalFinalPromptHandoff, gate: PreparationGateEvidence
) -> SemanticRendering:
    """Validate and render exact typed semantics, never parse free text or call the compiler."""
    source = decode_canonical_handoff(source)
    gate = PreparationGateEvidence.model_validate_json(canonical_bytes(gate))
    _check_source(source, gate)
    prompt = source.internal_final_prompt
    aliases = _aliases(gate.revision)
    lines = [
        "JEWELAI DESIGN INPUT 1.0.0",
        "Preserve requirements, prohibitions, KEEP and LOCKED values. "
        "Do not invent dimensions or promote references/unresolved items to requirements.",
    ]
    coverage = []

    def section(name, items):
        lines.append(name.upper())
        if not items:
            lines.append("NONE")
        for pointer, text in items:
            lines.append(text)
            coverage.append(
                SemanticCoverage(
                    source_pointer=pointer, rendered_section=name, rendered_ordinal=len(lines)
                )
            )

    facts = []
    for i, f in sorted(
        enumerate(prompt.design_facts), key=lambda pair: _alias(pair[1].target, aliases)
    ):
        if f.target == "references" and f.value:
            raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_SEMANTICS)
        value = (
            "NOT_APPLICABLE"
            if f.applicability == "not_applicable"
            else canonical_bytes(_safe_value(f.value, aliases, f.target)).decode()
        )
        facts.append(
            (
                f"/internal_final_prompt/design_facts/{i}",
                f"FACT {_alias(f.target, aliases)} = {value}; origin={f.origin}; "
                f"semantic_state={f.semantic_state.value}; provenance={f.provenance.value}; "
                f"confirmed={str(f.confirmed).lower()}; "
                f"locked={str(f.locked).lower()}",
            )
        )
    section("facts", facts)
    constraints = []
    for i, c in sorted(
        enumerate(prompt.constraints),
        key=lambda pair: (
            _alias(pair[1].target, aliases),
            pair[1].kind,
            pair[1].instruction,
            canonical_bytes(pair[1].value),
        ),
    ):
        kind = "KEEP" if c.kind == "preservation" else c.kind.upper()
        value = canonical_bytes(_safe_value(c.value, aliases, c.target)).decode()
        constraints.append(
            (
                f"/internal_final_prompt/constraints/{i}",
                f"{kind} {_alias(c.target, aliases)} = {value}; "
                f"instruction={canonical_bytes(c.instruction).decode()}",
            )
        )
    section("constraints", constraints)
    references = []
    for i, ref in enumerate(prompt.parametric_references):
        data = ref.model_dump(mode="json", exclude={"record_ids", "source_ids"})
        references.append(
            (
                f"/internal_final_prompt/parametric_references/{i}",
                "REFERENCE ONLY (not a requirement): " + canonical_bytes(data).decode(),
            )
        )
    section("references", references)
    disclosures = []
    for i, d in enumerate(prompt.disclosures):
        data = d.model_dump(mode="json", exclude={"sources", "concrete_target"}, exclude_none=True)
        disclosures.append(
            (
                f"/internal_final_prompt/disclosures/{i}",
                f"DISCLOSURE {_alias(d.concrete_target, aliases)} = "
                + canonical_bytes(data).decode(),
            )
        )
    section("disclosures", disclosures)
    section(
        "unresolved",
        [
            (
                f"/internal_final_prompt/unresolved_details/{i}",
                f"{_alias(u.target, aliases)}: {u.classification}; not an accepted requirement",
            )
            for i, u in sorted(
                enumerate(prompt.unresolved_details),
                key=lambda pair: (_alias(pair[1].target, aliases), pair[1].classification, pair[0]),
            )
        ],
    )
    text = "\n".join(lines)
    raw = text.encode("utf-8")
    if len(text) > RENDER_MAX_CHARACTERS or len(raw) > RENDER_MAX_BYTES:
        raise GenerationPreparationError(PreparationErrorCode.CAPACITY)
    return SemanticRendering(
        rendering_text=text,
        rendering_characters=len(text),
        rendering_utf8_bytes=len(raw),
        rendering_hash=hashlib.sha256(
            b"jewelai.preparation.render/jewelai.semantic-text/1.0.0\0" + raw
        ).hexdigest(),
        semantic_coverage=tuple(coverage),
    )


class GenerationPreparationPayload(ImmutableModel):
    """Wire schema; use GenerationPreparation to own a deeply immutable byte snapshot."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    preparation_id: UUID
    created_at: AwareDatetime
    organization_id: UUID
    session_id: UUID
    design_id: UUID
    product_state_revision_id: UUID
    enrichment_cycle_id: UUID
    enrichment_cycle_number: Annotated[StrictInt, Field(ge=1)]
    enrichment_result_hash: Sha256
    source_handoff: AnyCanonicalInternalFinalPromptHandoff
    gate_evidence: PreparationGateEvidence
    source_handoff_hash: Sha256
    source_bytes_sha256: Sha256
    gate_evidence_hash: Sha256
    execution: SemanticRendering
    artifact_hash: Sha256

    @field_serializer("created_at")
    def canonical_timestamp(self, value):
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")

    @model_validator(mode="after")
    def validate_preparation(self):
        prompt = self.source_handoff.internal_final_prompt
        if (
            any(
                getattr(self, key) != getattr(prompt, key)
                for key in (
                    "organization_id",
                    "session_id",
                    "design_id",
                    "product_state_revision_id",
                    "enrichment_cycle_id",
                    "enrichment_cycle_number",
                )
            )
            or self.enrichment_result_hash != prompt.enrichment_result_content_hash
        ):
            raise GenerationPreparationError(PreparationErrorCode.INTEGRITY)
        source_bytes = canonical_bytes(self.source_handoff)
        if len(source_bytes) + len(canonical_bytes(self.gate_evidence)) > SOURCE_MAX_BYTES:
            raise GenerationPreparationError(PreparationErrorCode.CAPACITY)
        if (
            self.source_handoff_hash != self.source_handoff.content_hash
            or self.source_bytes_sha256 != hashlib.sha256(source_bytes).hexdigest()
            or self.gate_evidence_hash
            != preparation_hash("jewelai.preparation.gate/1.0.0", self.gate_evidence)
        ):
            raise GenerationPreparationError(PreparationErrorCode.INTEGRITY)
        if self.execution != render_semantic_source(self.source_handoff, self.gate_evidence):
            raise GenerationPreparationError(PreparationErrorCode.INTEGRITY)
        if self.artifact_hash != preparation_hash(
            "jewelai.preparation.artifact/1.0.0",
            self.model_dump(mode="json", exclude={"artifact_hash"}),
        ):
            raise GenerationPreparationError(PreparationErrorCode.INTEGRITY)
        if len(canonical_bytes(self)) > ARTIFACT_MAX_BYTES:
            raise GenerationPreparationError(PreparationErrorCode.CAPACITY)
        return self


@dataclass(frozen=True, slots=True)
class GenerationPreparation:
    """Own exact validated canonical bytes; callers cannot mutate nested retained source values."""

    canonical: bytes

    def __post_init__(self):
        if not isinstance(self.canonical, bytes) or len(self.canonical) > ARTIFACT_MAX_BYTES:
            raise GenerationPreparationError(PreparationErrorCode.CAPACITY)
        payload = _strict_json(self.canonical)
        if payload.get("schema_version") != "1.0.0":
            raise GenerationPreparationError(PreparationErrorCode.UNSUPPORTED_VERSION)
        try:
            checked = GenerationPreparationPayload.model_validate_json(canonical_bytes(payload))
        except ValidationError:
            raise GenerationPreparationError(PreparationErrorCode.INTEGRITY) from None
        if canonical_bytes(checked) != self.canonical:
            raise GenerationPreparationError(PreparationErrorCode.INTEGRITY)

    @property
    def payload(self) -> GenerationPreparationPayload:
        return GenerationPreparationPayload.model_validate_json(self.canonical)

    @classmethod
    def model_validate_json(cls, value: bytes | str):
        if isinstance(value, str):
            try:
                value = value.encode("utf-8")
            except UnicodeError:
                raise GenerationPreparationError(PreparationErrorCode.INTEGRITY) from None
        return cls(value)

    def model_dump(self, *, mode="json"):
        return self.payload.model_dump(mode=mode)


def build_generation_preparation(
    source_handoff: AnyCanonicalInternalFinalPromptHandoff | object,
    gate_evidence: PreparationGateEvidence | object,
    *,
    preparation_id: UUID,
    created_at: datetime,
) -> GenerationPreparation:
    """Pure preparation. B2 must supply transaction-scoped, authenticated, verified evidence."""
    original_source = canonical_bytes(source_handoff)
    original_gate = canonical_bytes(gate_evidence)
    try:
        source = decode_canonical_handoff(source_handoff)
        gate = PreparationGateEvidence.model_validate_json(original_gate)
    except ValidationError:
        raise GenerationPreparationError(PreparationErrorCode.INVALID_SOURCE) from None
    if canonical_bytes(source) != original_source or canonical_bytes(gate) != original_gate:
        raise GenerationPreparationError(PreparationErrorCode.INTEGRITY)
    if len(canonical_bytes(source)) + len(canonical_bytes(gate)) > SOURCE_MAX_BYTES:
        raise GenerationPreparationError(PreparationErrorCode.CAPACITY)
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise GenerationPreparationError(PreparationErrorCode.INVALID_SOURCE)
    payload = {
        "schema_version": "1.0.0",
        "preparation_id": str(preparation_id),
        "created_at": created_at.astimezone(UTC)
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
        "enrichment_result_hash": source.internal_final_prompt.enrichment_result_content_hash,
        "source_handoff": source.model_dump(mode="json"),
        "gate_evidence": gate.model_dump(mode="json"),
        "source_handoff_hash": source.content_hash,
        "source_bytes_sha256": hashlib.sha256(canonical_bytes(source)).hexdigest(),
        "gate_evidence_hash": preparation_hash("jewelai.preparation.gate/1.0.0", gate),
        "execution": render_semantic_source(source, gate).model_dump(mode="json"),
    }
    payload["artifact_hash"] = preparation_hash("jewelai.preparation.artifact/1.0.0", payload)
    return GenerationPreparation(canonical_bytes(payload))
