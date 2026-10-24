"""Deterministic Step #12 description and provider-neutral final-prompt assembly.

The builder consumes one already-validated module snapshot. It does not parse messages, mutate
Product State, re-enrich, select a Knowledge release, or invoke a provider.
"""

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from jewelai_domain.dictionary import DictionaryLocale, DictionaryRegistry
from jewelai_domain.knowledge_policy import (
    PreservationIntent,
    RuntimeProvenance,
    RuntimeSemanticState,
)
from jewelai_domain.models import (
    Assumed,
    Derived,
    DesignRevision,
    Explicit,
    ImmutableModel,
    MessageSource,
    NotApplicable,
    Text,
)
from jewelai_domain.rules import BlockDecision, ReadyDecision, RuleDecision
from pydantic import Field, JsonValue, StringConstraints, ValidationError, model_validator

from .compiler import PromptValidationError, validate_compiled_prompt
from .enrichment import PromptEnrichmentResult
from .models import PromptTemplateBundle, Sha256

FINAL_PROMPT_SCHEMA_VERSION = "1.1.0"
DESCRIPTION_SCHEMA_VERSION = "1.0.0"
LongText = Annotated[str, StringConstraints(min_length=1, max_length=20_000, pattern=r"\S")]


class FinalPromptReadiness(StrEnum):
    READY = "ready"
    READY_WITH_UNRESOLVED = "ready_with_unresolved"
    BLOCKED = "blocked"


class FinalPromptInputErrorCode(StrEnum):
    INVALID_SNAPSHOT = "invalid_snapshot"
    STALE_REVISION = "stale_revision"
    ENRICHMENT_CYCLE_MISMATCH = "enrichment_cycle_mismatch"
    KNOWLEDGE_RELEASE_MISMATCH = "knowledge_release_mismatch"
    ARTIFACT_MISMATCH = "artifact_mismatch"
    CROSS_SESSION_LINEAGE = "cross_session_lineage"
    INVALID_ENRICHMENT_STATE = "invalid_enrichment_state"


class FinalPromptInputError(ValueError):
    """Typed fail-closed error for inconsistent Step #12 inputs."""

    def __init__(self, code: FinalPromptInputErrorCode, detail: str):
        super().__init__(detail)
        self.code = code


class KnowledgeReleaseReference(ImmutableModel):
    package_id: str
    artifact_version: str
    runtime_sha256: Sha256
    validation_report_sha256: Sha256


class FinalPromptArtifactVersions(ImmutableModel):
    design_schema_version: str
    dictionary_artifact_version: str
    question_artifact_version: str
    rules_artifact_version: str
    prompt_template_artifact_version: str
    enrichment_version: str


class FinalPromptDecisionLineage(ImmutableModel):
    """Normalized immutable evidence from existing clarification/correction results."""

    kind: Literal["clarification", "correction"]
    session_id: UUID
    decision_id: str
    decision: str
    outcome: str
    target: str | None = None
    selected_value: JsonValue = None
    source_revision_id: UUID
    resulting_revision_id: UUID | None = None
    applies_to_revision_id: UUID
    knowledge_package_id: str
    knowledge_artifact_version: str
    knowledge_runtime_sha256: Sha256
    knowledge_validation_report_sha256: Sha256
    question_artifact_version: str | None = None
    rules_artifact_version: str | None = None
    blocks_progression: bool = False
    content_hash: Sha256


class FinalPromptConstraintEvidence(ImmutableModel):
    """Versioned, hashed evidence for explicit constraints outside canonical schema fields."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    evidence_id: Annotated[str, StringConstraints(pattern=r"^constraint_[0-9a-f]{24}$")]
    session_id: UUID
    organization_id: UUID
    kind: Literal["requirement", "prohibition", "preservation"]
    status: Literal["active", "superseded", "rejected", "unresolved"]
    acceptance: Literal["user_explicit", "user_accepted", "rejected", "unresolved"]
    semantic_subject: str | None = None
    canonical_target: str | None = None
    normalized_instruction: Text | None = None
    original_wording: Text
    source: MessageSource
    source_candidate_id: str
    source_span_start: int = Field(ge=0)
    source_span_end: int = Field(gt=0)
    source_revision_id: UUID
    source_enrichment_cycle_id: UUID
    superseded_by_evidence_id: str | None = None
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_contract(self):
        if self.source_span_end <= self.source_span_start:
            raise ValueError("constraint evidence span is invalid")
        if self.status == "active":
            if (
                self.acceptance not in {"user_explicit", "user_accepted"}
                or self.semantic_subject is None
                or self.normalized_instruction is None
                or self.superseded_by_evidence_id is not None
            ):
                raise ValueError("active constraint evidence lacks authoritative semantics")
        elif self.status == "superseded":
            if self.superseded_by_evidence_id is None:
                raise ValueError("superseded constraint evidence requires replacement lineage")
        elif self.superseded_by_evidence_id is not None:
            raise ValueError("only superseded evidence may reference a replacement")
        if self.content_hash != _hash(self.model_dump(mode="json", exclude={"content_hash"})):
            raise ValueError("constraint evidence content hash mismatch")
        return self


class FinalPromptSnapshot(ImmutableModel):
    """Explicit single-revision module snapshot supplied by the future runtime orchestrator."""

    session_id: UUID
    organization_id: UUID
    locale: Literal["en", "ru"]
    revision: DesignRevision
    enrichment_cycle_id: UUID
    latest_enrichment_cycle_id: UUID
    enrichment_cycle_number: int = Field(ge=1)
    enrichment_result: PromptEnrichmentResult
    knowledge_release: KnowledgeReleaseReference
    artifact_versions: FinalPromptArtifactVersions
    rule_decision: RuleDecision
    decision_lineage: tuple[FinalPromptDecisionLineage, ...] = ()
    constraint_evidence: tuple[FinalPromptConstraintEvidence, ...] = ()

    @model_validator(mode="after")
    def validate_stable_lineage_order(self):
        keys = [(item.kind, item.decision_id, item.content_hash) for item in self.decision_lineage]
        if keys != sorted(keys):
            raise ValueError("decision lineage must use stable kind/ID/hash order")
        if len(set(keys)) != len(keys):
            raise ValueError("decision lineage entries must be unique")
        evidence_keys = tuple(item.evidence_id for item in self.constraint_evidence)
        if evidence_keys != tuple(sorted(evidence_keys)):
            raise ValueError("constraint evidence must use stable evidence-ID order")
        if len(set(evidence_keys)) != len(evidence_keys):
            raise ValueError("constraint evidence IDs must be unique")
        by_id = {item.evidence_id: item for item in self.constraint_evidence}
        active_subjects: set[str] = set()
        for item in self.constraint_evidence:
            if item.session_id != self.session_id or item.organization_id != self.organization_id:
                raise ValueError("constraint evidence belongs to another session scope")
            if item.status == "active":
                if item.semantic_subject in active_subjects:
                    raise ValueError("conflicting active constraint evidence cannot coexist")
                active_subjects.add(item.semantic_subject)
            if item.status == "superseded":
                replacement = by_id.get(item.superseded_by_evidence_id)
                if replacement is None or replacement.semantic_subject != item.semantic_subject:
                    raise ValueError("constraint supersession lineage is invalid")
        return self


class FinalPromptDesignFact(ImmutableModel):
    target: str
    applicability: Literal["value", "not_applicable"]
    value: JsonValue = None
    origin: Literal["explicit", "derived", "assumed"]
    semantic_state: RuntimeSemanticState
    provenance: RuntimeProvenance
    confirmed: bool
    locked: bool
    source_ids: tuple[str, ...]


class FinalPromptConstraint(ImmutableModel):
    kind: Literal["requirement", "prohibition", "preservation"]
    target: str
    value: JsonValue = None
    instruction: str
    source_ids: tuple[str, ...] = ()


class FinalPromptUnresolvedDetail(ImmutableModel):
    target: str
    classification: Literal[
        "missing",
        "ambiguous",
        "unaccepted_recommendation",
        "skipped",
        "unknown",
        "deferred",
    ]
    blocking: bool
    source_ids: tuple[str, ...] = ()


class FinalPromptEnrichmentEvidence(ImmutableModel):
    target: str
    semantic_state: RuntimeSemanticState
    provenance: RuntimeProvenance
    outcome: Literal["APPLIED", "KEPT", "BLOCKED"]
    source_id: str
    preservation: PreservationIntent
    accepted_as_requirement: bool


class UserReadableJewelryDescription(ImmutableModel):
    schema_version: Literal["1.0.0"] = DESCRIPTION_SCHEMA_VERSION
    locale: Literal["en", "ru"]
    authoritative_revision_id: UUID
    text: LongText
    unresolved_summary: tuple[str, ...]
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_hash(self):
        if self.content_hash != _hash(self.model_dump(mode="json", exclude={"content_hash"})):
            raise ValueError("user-readable description content hash mismatch")
        return self


class InternalFinalPrompt(ImmutableModel):
    """Official provider-neutral Prompt Enrichment Module v1 handoff artifact."""

    schema_version: Literal["1.1.0"] = FINAL_PROMPT_SCHEMA_VERSION
    session_id: UUID
    organization_id: UUID
    design_id: UUID
    product_state_revision_id: UUID
    enrichment_cycle_id: UUID
    enrichment_cycle_number: int
    locale: Literal["en", "ru"]
    readiness: FinalPromptReadiness
    readiness_reason: str
    description_content_hash: Sha256
    prompt_text: LongText
    design_facts: tuple[FinalPromptDesignFact, ...]
    constraints: tuple[FinalPromptConstraint, ...]
    unresolved_details: tuple[FinalPromptUnresolvedDetail, ...]
    enrichment_evidence: tuple[FinalPromptEnrichmentEvidence, ...]
    decision_lineage: tuple[FinalPromptDecisionLineage, ...]
    constraint_evidence: tuple[FinalPromptConstraintEvidence, ...]
    knowledge_release: KnowledgeReleaseReference
    artifact_versions: FinalPromptArtifactVersions
    enrichment_result_content_hash: Sha256
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_hash(self):
        if self.content_hash != _hash(self.model_dump(mode="json", exclude={"content_hash"})):
            raise ValueError("Internal Final Prompt content hash mismatch")
        return self


class FinalPromptAssembly(ImmutableModel):
    description: UserReadableJewelryDescription
    internal_final_prompt: InternalFinalPrompt

    @model_validator(mode="after")
    def validate_shared_snapshot(self):
        prompt = self.internal_final_prompt
        if (
            self.description.authoritative_revision_id != prompt.product_state_revision_id
            or self.description.locale != prompt.locale
            or self.description.content_hash != prompt.description_content_hash
        ):
            raise ValueError("description and Internal Final Prompt do not share one snapshot")
        return self


def assemble_internal_final_prompt(
    snapshot: FinalPromptSnapshot | object,
    *,
    dictionary: DictionaryRegistry,
    templates: PromptTemplateBundle,
) -> FinalPromptAssembly:
    """Build both Step #12 outputs from one immutable, fail-closed snapshot."""

    try:
        snapshot = FinalPromptSnapshot.model_validate(snapshot)
    except ValidationError as exc:
        raise FinalPromptInputError(
            FinalPromptInputErrorCode.INVALID_SNAPSHOT,
            "final-prompt snapshot failed validation",
        ) from exc
    templates = PromptTemplateBundle.model_validate(templates)
    _validate_snapshot(snapshot, dictionary=dictionary, templates=templates)

    facts = _design_facts(snapshot)
    constraints = _constraints(snapshot, facts)
    unresolved = _unresolved_details(snapshot)
    evidence = _enrichment_evidence(snapshot, facts)
    readiness, readiness_reason = _readiness(snapshot, unresolved)
    description = _description(snapshot, dictionary, facts, constraints, unresolved)
    prompt_text = _render_internal_prompt(
        description,
        facts,
        constraints,
        unresolved,
        readiness,
    )
    payload = {
        "schema_version": FINAL_PROMPT_SCHEMA_VERSION,
        "session_id": snapshot.session_id,
        "organization_id": snapshot.organization_id,
        "design_id": snapshot.revision.design_id,
        "product_state_revision_id": snapshot.revision.revision_id,
        "enrichment_cycle_id": snapshot.enrichment_cycle_id,
        "enrichment_cycle_number": snapshot.enrichment_cycle_number,
        "locale": snapshot.locale,
        "readiness": readiness,
        "readiness_reason": readiness_reason,
        "description_content_hash": description.content_hash,
        "prompt_text": prompt_text,
        "design_facts": facts,
        "constraints": constraints,
        "unresolved_details": unresolved,
        "enrichment_evidence": evidence,
        "decision_lineage": snapshot.decision_lineage,
        "constraint_evidence": snapshot.constraint_evidence,
        "knowledge_release": snapshot.knowledge_release,
        "artifact_versions": snapshot.artifact_versions,
        "enrichment_result_content_hash": snapshot.enrichment_result.content_hash,
    }
    internal = InternalFinalPrompt(**payload, content_hash=_hash(_json(payload)))
    return FinalPromptAssembly(description=description, internal_final_prompt=internal)


def _validate_snapshot(snapshot, *, dictionary, templates):
    revision = snapshot.revision
    enrichment = snapshot.enrichment_result
    compiled = enrichment.compiled_prompt
    if (
        enrichment.design_revision_id != str(revision.revision_id)
        or compiled.specification_revision_id != revision.revision_id
        or compiled.design_id != revision.design_id
    ):
        raise FinalPromptInputError(
            FinalPromptInputErrorCode.STALE_REVISION,
            "Product State and enrichment cycle revisions do not match",
        )
    if snapshot.enrichment_cycle_id != snapshot.latest_enrichment_cycle_id:
        raise FinalPromptInputError(
            FinalPromptInputErrorCode.ENRICHMENT_CYCLE_MISMATCH,
            "supplied enrichment cycle is not the latest authoritative cycle",
        )
    release = snapshot.knowledge_release
    if (
        enrichment.knowledge_package_id != release.package_id
        or enrichment.knowledge_artifact_version != release.artifact_version
        or enrichment.knowledge_runtime_sha256 != release.runtime_sha256
        or enrichment.knowledge_validation_report_sha256 != release.validation_report_sha256
    ):
        raise FinalPromptInputError(
            FinalPromptInputErrorCode.KNOWLEDGE_RELEASE_MISMATCH,
            "enrichment cycle does not match the pinned verified Knowledge release",
        )
    versions = snapshot.artifact_versions
    if (
        versions.design_schema_version != revision.schema_version
        or versions.dictionary_artifact_version != dictionary.artifact_version
        or versions.rules_artifact_version != snapshot.rule_decision.rules_artifact_version
        or versions.prompt_template_artifact_version != templates.artifact_version
        or versions.prompt_template_artifact_version != compiled.template_artifact_version
        or versions.enrichment_version != enrichment.enrichment_version
    ):
        raise FinalPromptInputError(
            FinalPromptInputErrorCode.ARTIFACT_MISMATCH,
            "final-prompt artifact versions do not match the supplied snapshot",
        )
    try:
        validate_compiled_prompt(compiled, revision, templates)
    except PromptValidationError as exc:
        raise FinalPromptInputError(
            FinalPromptInputErrorCode.INVALID_ENRICHMENT_STATE,
            "enrichment CompiledPrompt does not match the authoritative revision",
        ) from exc
    for item in snapshot.decision_lineage:
        if item.session_id != snapshot.session_id:
            raise FinalPromptInputError(
                FinalPromptInputErrorCode.CROSS_SESSION_LINEAGE,
                "clarification or correction evidence belongs to another session",
            )
        if item.applies_to_revision_id != revision.revision_id:
            raise FinalPromptInputError(
                FinalPromptInputErrorCode.STALE_REVISION,
                "clarification or correction evidence targets another Product State revision",
            )
        if (
            item.knowledge_package_id != release.package_id
            or item.knowledge_artifact_version != release.artifact_version
            or item.knowledge_runtime_sha256 != release.runtime_sha256
            or item.knowledge_validation_report_sha256 != release.validation_report_sha256
        ):
            raise FinalPromptInputError(
                FinalPromptInputErrorCode.KNOWLEDGE_RELEASE_MISMATCH,
                "clarification or correction evidence uses another Knowledge release",
            )
        if item.kind == "clarification" and (
            item.question_artifact_version != versions.question_artifact_version
            or item.rules_artifact_version != versions.rules_artifact_version
        ):
            raise FinalPromptInputError(
                FinalPromptInputErrorCode.ARTIFACT_MISMATCH,
                "clarification evidence uses different question or rules artifacts",
            )


def _design_facts(snapshot) -> tuple[FinalPromptDesignFact, ...]:
    matrix = {item.target: item for item in snapshot.enrichment_result.final_matrix}
    facts = []
    for entry in snapshot.enrichment_result.compiled_prompt.specification_entries:
        cell = matrix.get(entry.concrete_target)
        expected_value = None if entry.applicability == "not_applicable" else entry.value
        if cell is None:
            semantic_state, provenance, source_ids = _canonical_metadata(
                snapshot.revision, entry.concrete_target
            )
        else:
            semantic_state = cell.semantic_state
            provenance = cell.provenance
            source_ids = cell.source_ids
        if cell is not None and (
            cell.value != expected_value
            or cell.confirmed != entry.confirmed
            or cell.locked != entry.locked
        ):
            raise FinalPromptInputError(
                FinalPromptInputErrorCode.INVALID_ENRICHMENT_STATE,
                f"final Matrix disagrees with Product State: {entry.concrete_target}",
            )
        if provenance is None:
            raise FinalPromptInputError(
                FinalPromptInputErrorCode.INVALID_ENRICHMENT_STATE,
                f"authoritative target has no provenance: {entry.concrete_target}",
            )
        facts.append(
            FinalPromptDesignFact(
                target=entry.concrete_target,
                applicability=entry.applicability,
                value=expected_value,
                origin=entry.origin,
                semantic_state=semantic_state,
                provenance=provenance,
                confirmed=entry.confirmed,
                locked=entry.locked,
                source_ids=source_ids,
            )
        )
    authoritative_targets = {item.target for item in facts}
    for cell in snapshot.enrichment_result.final_matrix:
        if (
            cell.semantic_state == RuntimeSemanticState.ACCEPTED
            and cell.provenance == RuntimeProvenance.USER_ACCEPTED_RECOMMENDATION
            and cell.target not in authoritative_targets
        ):
            raise FinalPromptInputError(
                FinalPromptInputErrorCode.INVALID_ENRICHMENT_STATE,
                "accepted enrichment is absent from authoritative Product State",
            )
    return tuple(facts)


def _canonical_metadata(revision, target):
    state = _canonical_state(revision, target)
    if isinstance(state, NotApplicable):
        return (
            RuntimeSemanticState.NOT_APPLICABLE,
            RuntimeProvenance.USER_CONFIRMED,
            (state.source.message_id,),
        )
    if isinstance(state, Explicit):
        provenance = (
            RuntimeProvenance.USER_CONFIRMED
            if state.confirmed
            else RuntimeProvenance.USER_EXPLICIT_LATEST
        )
        return RuntimeSemanticState.EXPLICIT, provenance, (state.source.message_id,)
    if isinstance(state, Derived):
        if state.confirmed:
            semantic = RuntimeSemanticState.ACCEPTED
            provenance = RuntimeProvenance.USER_ACCEPTED_RECOMMENDATION
        else:
            semantic = RuntimeSemanticState.RECOMMENDED
            provenance = RuntimeProvenance.KNOWLEDGE_INFERRED
        source_ids = tuple(
            item.record_id if hasattr(item, "record_id") else item.rule_id for item in state.sources
        )
        return semantic, provenance, source_ids
    if isinstance(state, Assumed):
        provenance = (
            RuntimeProvenance.USER_CONFIRMED
            if state.confirmed
            else RuntimeProvenance.VISUALIZATION_ASSUMPTION
        )
        return RuntimeSemanticState.ASSUMED, provenance, (state.source.rule_id,)
    raise FinalPromptInputError(
        FinalPromptInputErrorCode.INVALID_ENRICHMENT_STATE,
        f"authoritative target cannot be resolved from Product State: {target}",
    )


def _canonical_state(revision, target):
    parts = target.split(".")
    design = revision.design
    if parts[0] == "side_stones":
        if len(parts) < 3:
            return None
        group = next((item for item in design.side_stones if item.group_id == parts[1]), None)
        if group is None:
            return None
        if parts[2] == "quantity":
            return group.quantity
        if len(parts) == 4 and parts[2] == "stones":
            return getattr(group.stones, parts[3], None)
        return None
    current = design
    for part in parts:
        current = getattr(current, part, None)
        if current is None:
            return None
    return current


def _constraints(snapshot, facts) -> tuple[FinalPromptConstraint, ...]:
    constraints = []
    by_target = {item.target: item for item in facts}
    disclosures = {
        item.concrete_target: item
        for item in snapshot.enrichment_result.compiled_prompt.disclosures
    }
    for fact in facts:
        if fact.applicability == "not_applicable":
            disclosure = disclosures.get(fact.target)
            reason = disclosure.reason if disclosure is not None else None
            constraints.append(
                FinalPromptConstraint(
                    kind="prohibition",
                    target=fact.target,
                    instruction=reason
                    or "Do not include this explicitly inapplicable design element.",
                    source_ids=fact.source_ids,
                )
            )
        else:
            constraints.append(
                FinalPromptConstraint(
                    kind="requirement",
                    target=fact.target,
                    value=fact.value,
                    instruction="Preserve this authoritative design value.",
                    source_ids=fact.source_ids,
                )
            )
        if fact.locked:
            constraints.append(
                FinalPromptConstraint(
                    kind="preservation",
                    target=fact.target,
                    value=fact.value,
                    instruction="This confirmed locked value must not change.",
                    source_ids=fact.source_ids,
                )
            )
    existing = {(item.kind, item.target) for item in constraints}
    for decision in snapshot.enrichment_result.decisions:
        if (
            decision.proposal.preservation in {PreservationIntent.KEEP, PreservationIntent.LOCKED}
            and decision.target in by_target
            and ("preservation", decision.target) not in existing
        ):
            fact = by_target[decision.target]
            constraints.append(
                FinalPromptConstraint(
                    kind="preservation",
                    target=fact.target,
                    value=fact.value,
                    instruction="Keep the existing authoritative design value unchanged.",
                    source_ids=tuple(sorted(set(fact.source_ids + (decision.proposal.source_id,)))),
                )
            )
            existing.add(("preservation", decision.target))
    for evidence in snapshot.constraint_evidence:
        if evidence.status != "active":
            continue
        constraints.append(
            FinalPromptConstraint(
                kind=evidence.kind,
                target=evidence.canonical_target or evidence.semantic_subject,
                instruction=evidence.normalized_instruction,
                source_ids=(evidence.evidence_id, evidence.source.message_id),
            )
        )
    return tuple(sorted(constraints, key=lambda item: (item.target, item.kind)))


def _unresolved_details(snapshot) -> tuple[FinalPromptUnresolvedDetail, ...]:
    items = []
    for cell in snapshot.enrichment_result.final_matrix:
        classification = {
            RuntimeSemanticState.MISSING: "missing",
            RuntimeSemanticState.AMBIGUOUS: "ambiguous",
            RuntimeSemanticState.RECOMMENDED: "unaccepted_recommendation",
        }.get(cell.semantic_state)
        if classification is not None:
            items.append(
                FinalPromptUnresolvedDetail(
                    target=cell.target,
                    classification=classification,
                    blocking=False,
                    source_ids=cell.source_ids,
                )
            )
    for lineage in snapshot.decision_lineage:
        classification = {
            "SKIPPED": "skipped",
            "UNKNOWN": "unknown",
            "DEFERRED": "deferred",
        }.get(lineage.outcome.upper())
        if classification is not None and lineage.target is not None:
            items.append(
                FinalPromptUnresolvedDetail(
                    target=lineage.target,
                    classification=classification,
                    blocking=lineage.blocks_progression,
                    source_ids=(lineage.decision_id,),
                )
            )
    for evidence in snapshot.constraint_evidence:
        if evidence.status == "unresolved":
            items.append(
                FinalPromptUnresolvedDetail(
                    target=evidence.semantic_subject or "constraint.unresolved",
                    classification="ambiguous",
                    blocking=False,
                    source_ids=(evidence.evidence_id, evidence.source.message_id),
                )
            )
    unique = {
        (item.target, item.classification, item.blocking, item.source_ids): item for item in items
    }
    return tuple(
        unique[key] for key in sorted(unique, key=lambda item: (item[0], item[1], item[2], item[3]))
    )


def _enrichment_evidence(snapshot, facts) -> tuple[FinalPromptEnrichmentEvidence, ...]:
    accepted = {
        item.target
        for item in facts
        if item.semantic_state == RuntimeSemanticState.ACCEPTED
        and item.provenance == RuntimeProvenance.USER_ACCEPTED_RECOMMENDATION
    }
    return tuple(
        FinalPromptEnrichmentEvidence(
            target=decision.target,
            semantic_state=decision.proposal.semantic_state,
            provenance=decision.proposal.provenance,
            outcome=decision.outcome,
            source_id=decision.proposal.source_id,
            preservation=decision.proposal.preservation,
            accepted_as_requirement=decision.target in accepted,
        )
        for decision in snapshot.enrichment_result.decisions
    )


def _readiness(snapshot, unresolved):
    if isinstance(snapshot.rule_decision, BlockDecision):
        return FinalPromptReadiness.BLOCKED, snapshot.rule_decision.reason
    if not isinstance(snapshot.rule_decision, ReadyDecision):
        return (
            FinalPromptReadiness.BLOCKED,
            "The existing Rules Engine has not declared the Product State ready.",
        )
    if any(item.blocks_progression for item in snapshot.decision_lineage):
        return FinalPromptReadiness.BLOCKED, "An authoritative clarification remains blocking."
    if unresolved:
        return (
            FinalPromptReadiness.READY_WITH_UNRESOLVED,
            "The Rules Engine is ready; noncritical unresolved details remain explicit.",
        )
    return FinalPromptReadiness.READY, snapshot.rule_decision.reason


def _description(snapshot, dictionary, facts, constraints, unresolved):
    locale = DictionaryLocale(snapshot.locale)
    fact_map = {item.target: item for item in facts if item.applicability == "value"}
    sentences = []
    jewelry_type = fact_map.get("jewelry_type")
    if jewelry_type is not None:
        label = _value_text(jewelry_type.value, dictionary, locale)
        sentences.append(
            f"Current design: {label}." if snapshot.locale == "en" else f"Текущий дизайн: {label}."
        )
    metal = _component_sentence("metal", fact_map, dictionary, locale, snapshot.locale)
    if metal:
        sentences.append(metal)
    center = _component_sentence("center_stone", fact_map, dictionary, locale, snapshot.locale)
    if center:
        sentences.append(center)
    group_prefixes = sorted(
        {
            ".".join(item.target.split(".")[:2])
            for item in facts
            if item.target.startswith("side_stones.")
        }
    )
    for index, prefix in enumerate(group_prefixes, start=1):
        sentence = _component_sentence(
            prefix, fact_map, dictionary, locale, snapshot.locale, group_number=index
        )
        if sentence:
            sentences.append(sentence)
    for target, en_label, ru_label in (
        ("style", "Style", "Стиль"),
        ("visual_constraints", "Visual requirements", "Визуальные требования"),
        ("references", "References", "Референсы"),
    ):
        fact = fact_map.get(target)
        if fact is not None:
            sentences.append(
                f"{en_label if snapshot.locale == 'en' else ru_label}: "
                f"{_value_text(fact.value, dictionary, locale, target=target)}."
            )
    prohibitions = [item for item in constraints if item.kind == "prohibition"]
    if prohibitions:
        labels = ", ".join(
            f"{_target_label(item.target, snapshot.locale)} ({item.instruction})"
            for item in prohibitions
        )
        sentences.append(
            f"Explicitly excluded: {labels}."
            if snapshot.locale == "en"
            else f"Явно исключено: {labels}."
        )
    noncanonical_requirements = [
        item for item in constraints if item.kind == "requirement" and item.target not in fact_map
    ]
    if noncanonical_requirements:
        labels = "; ".join(item.instruction for item in noncanonical_requirements)
        sentences.append(
            f"Explicit requirements: {labels}"
            if snapshot.locale == "en"
            else f"Явные требования: {labels}"
        )
    noncanonical_preservation = [
        item for item in constraints if item.kind == "preservation" and item.target not in fact_map
    ]
    if noncanonical_preservation:
        labels = "; ".join(item.instruction for item in noncanonical_preservation)
        sentences.append(
            f"Preserve: {labels}" if snapshot.locale == "en" else f"Сохранить: {labels}"
        )
    unconfirmed = [item for item in facts if not item.confirmed]
    if unconfirmed:
        labels = ", ".join(_target_label(item.target, snapshot.locale) for item in unconfirmed)
        sentences.append(
            f"Included for review, not confirmed: {labels}."
            if snapshot.locale == "en"
            else f"Добавлено для проверки, но не подтверждено: {labels}."
        )
    unresolved_summary = tuple(
        f"{_target_label(item.target, snapshot.locale)}: "
        f"{_classification_label(item.classification, snapshot.locale)}"
        for item in unresolved
    )
    if unresolved_summary:
        sentences.append(
            ("Still open: " if snapshot.locale == "en" else "Остается уточнить: ")
            + "; ".join(unresolved_summary)
            + "."
        )
    text = " ".join(sentences)
    payload = {
        "schema_version": DESCRIPTION_SCHEMA_VERSION,
        "locale": snapshot.locale,
        "authoritative_revision_id": snapshot.revision.revision_id,
        "text": text,
        "unresolved_summary": unresolved_summary,
    }
    return UserReadableJewelryDescription(**payload, content_hash=_hash(_json(payload)))


def _component_sentence(prefix, facts, dictionary, locale, language, group_number=None):
    members = []
    prefix_dot = f"{prefix}."
    for target in sorted(facts):
        if target.startswith(prefix_dot):
            field = target.removeprefix(prefix_dot).removeprefix("stones.")
            members.append(
                f"{_field_label(field, language)} "
                f"{_value_text(facts[target].value, dictionary, locale, target=target)}"
            )
    if not members:
        return None
    if prefix == "metal":
        heading = "Metal" if language == "en" else "Металл"
    elif prefix == "center_stone":
        heading = "Center stone" if language == "en" else "Центральный камень"
    else:
        heading = (
            f"Side-stone group {group_number}"
            if language == "en"
            else f"Группа боковых камней {group_number}"
        )
    return f"{heading}: {', '.join(members)}."


def _value_text(value, dictionary, locale, *, target=None):
    if target == "references" and isinstance(value, list):
        count = len(value)
        return (
            f"{count} private design reference{'s' if count != 1 else ''}"
            if locale == DictionaryLocale.EN
            else f"{count} приватных референса дизайна"
        )
    if target == "visual_constraints" and isinstance(value, list):
        return "; ".join(str(item.get("instruction", "")) for item in value)
    if isinstance(value, str):
        try:
            return dictionary[value].canonical_terms.for_locale(locale)
        except KeyError:
            return value.replace("_", " ")
    if isinstance(value, list):
        return ", ".join(_value_text(item, dictionary, locale) for item in value)
    if isinstance(value, dict):
        if set(value) >= {"length", "width", "depth"}:
            parts = [value[name]["value"] for name in ("length", "width", "depth")]
            unit = value["length"]["unit"]
            return f"{' × '.join(_number(item) for item in parts)} {unit}"
        if set(value) >= {"value", "unit"}:
            return f"{_number(value['value'])} {value['unit']}"
        if set(value) >= {"value", "scope"}:
            scope = _scope_label(value["scope"], locale.value)
            return f"{value['value']} {scope}"
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def _number(value):
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


def _scope_label(scope, locale):
    labels = {
        "en": {"per_side": "per side", "per_item": "per item", "per_pair": "per pair"},
        "ru": {"per_side": "с каждой стороны", "per_item": "на изделие", "per_pair": "на пару"},
    }
    return labels[locale].get(scope, scope.replace("_", " "))


def _field_label(field, locale):
    labels = {
        "en": {
            "material": "material",
            "color": "color",
            "purity": "purity",
            "finish": "finish",
            "shape": "shape",
            "cut": "cut",
            "weight": "weight",
            "dimensions": "dimensions",
            "setting": "setting",
            "orientation": "orientation",
            "quantity": "quantity",
            "shank": "shank",
            "gallery": "gallery",
            "basket": "basket",
            "clasp": "clasp",
            "setting_height": "setting height",
            "shank_width": "band width",
            "thickness": "thickness",
        },
        "ru": {
            "material": "материал",
            "color": "цвет",
            "purity": "проба",
            "finish": "отделка",
            "shape": "форма",
            "cut": "огранка",
            "weight": "вес",
            "dimensions": "размеры",
            "setting": "закрепка",
            "orientation": "ориентация",
            "quantity": "количество",
            "shank": "шинка",
            "gallery": "галерея",
            "basket": "корзина",
            "clasp": "застежка",
            "setting_height": "высота закрепки",
            "shank_width": "ширина шинки",
            "thickness": "толщина",
        },
    }
    return labels[locale].get(field, field.replace("_", " "))


def _target_label(target, locale):
    parts = target.split(".")
    if parts[0] == "side_stones":
        field = parts[-1]
        return (
            f"side-stone {_field_label(field, locale)}"
            if locale == "en"
            else f"{_field_label(field, locale)} боковых камней"
        )
    headings = {
        "jewelry_type": ("jewelry type", "тип украшения"),
        "metal": ("metal", "металл"),
        "center_stone": ("center stone", "центральный камень"),
        "construction": ("construction", "конструкция"),
        "style": ("style", "стиль"),
        "references": ("design references", "референсы дизайна"),
        "visual_constraints": ("visual requirements", "визуальные требования"),
    }
    base = headings.get(parts[0], (parts[0].replace("_", " "), parts[0].replace("_", " ")))
    heading = base[0 if locale == "en" else 1]
    if len(parts) == 1:
        return heading
    return f"{heading} {_field_label(parts[-1], locale)}"


def _classification_label(classification, locale):
    labels = {
        "en": {
            "missing": "not specified",
            "ambiguous": "ambiguous",
            "unaccepted_recommendation": "optional recommendation not accepted",
            "skipped": "skipped",
            "unknown": "unknown",
            "deferred": "deferred",
        },
        "ru": {
            "missing": "не указано",
            "ambiguous": "неоднозначно",
            "unaccepted_recommendation": "непринятая необязательная рекомендация",
            "skipped": "пропущено",
            "unknown": "неизвестно",
            "deferred": "отложено",
        },
    }
    return labels[locale][classification]


def _render_internal_prompt(description, facts, constraints, unresolved, readiness):
    lines = [
        f"JEWELAI INTERNAL FINAL PROMPT {FINAL_PROMPT_SCHEMA_VERSION}",
        f"READINESS: {readiness.value}",
        "USER-READABLE DESIGN DESCRIPTION",
        description.text,
        "AUTHORITATIVE DESIGN FACTS",
    ]
    lines.extend(
        f"{item.target} = "
        + (
            "NOT_APPLICABLE"
            if item.applicability == "not_applicable"
            else json.dumps(item.value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        for item in facts
    )
    lines.append("CONSTRAINTS AND PRESERVATION")
    lines.extend(
        f"{item.kind.upper()}: {item.target} = "
        f"{json.dumps(item.value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}; "
        f"instruction={json.dumps(item.instruction, ensure_ascii=False)}"
        for item in constraints
    )
    lines.append("UNRESOLVED DETAILS")
    lines.extend(
        f"{item.target}: {item.classification}; blocking={str(item.blocking).lower()}"
        for item in unresolved
    )
    return "\n".join(lines)


def _json(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    return value


def _hash(payload) -> str:
    canonical = json.dumps(
        _json(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
