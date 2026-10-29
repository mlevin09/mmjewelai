"""Deterministic Knowledge Library enrichment matrix for prompt compilation."""

import hashlib
import json
from typing import Annotated, Literal

from jewelai_domain.knowledge_activation import Sha256
from jewelai_domain.knowledge_policy import (
    KnowledgePolicyEngine,
    KnowledgeRuntimeState,
    PreservationIntent,
    RuntimeParameterState,
    RuntimeProvenance,
    RuntimeSemanticState,
    RuntimeStateProposal,
    build_knowledge_runtime_state,
    validate_proposal_authority,
)
from jewelai_domain.knowledge_runtime import (
    AnyActiveKnowledge,
    AnyCompiledKnowledge,
    AnyKnowledgeStore,
    AnyValidationReport,
    validate_compiled_knowledge,
)
from jewelai_domain.models import (
    Assumed,
    Derived,
    Explicit,
    ImmutableModel,
    KnownValue,
    NotApplicable,
    Text,
    Version,
)
from jewelai_domain.models_v1_1 import AnyDesignRevision, validate_design_revision
from pydantic import Field, JsonValue, TypeAdapter, field_validator, model_validator

from .models import (
    CompiledPrompt,
    PromptConstraint,
    PromptDisclosure,
    PromptTemplateBundle,
    SpecificationEntry,
)
from .revision_projection import RevisionProjection, project_revision

PROMPT_ENRICHMENT_VERSION = "1.3.0"


class ParametricReferenceDimensions(ImmutableModel):
    diameter_mm: float | None = Field(default=None, gt=0)
    length_mm: float | None = Field(default=None, gt=0)
    width_mm: float | None = Field(default=None, gt=0)
    depth_mm: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_geometry(self):
        round_geometry = self.diameter_mm is not None
        fancy_geometry = self.length_mm is not None or self.width_mm is not None
        if round_geometry and fancy_geometry:
            raise ValueError("parametric reference must use diameter or length/width, not both")
        if not round_geometry and not (self.length_mm is not None and self.width_mm is not None):
            raise ValueError("parametric reference requires diameter or both length and width")
        return self


class ParametricEnrichmentReference(ImmutableModel):
    target: Literal["center_stone.dimensions"]
    material_id: str
    shape_id: str
    weight_ct: float = Field(gt=0)
    dimensions: ParametricReferenceDimensions
    estimate_kind: Literal[
        "SOURCE_REFERENCE",
        "APPROXIMATE_CALIBRATION",
        "STANDARD_PROPORTION_REFERENCE",
    ]
    record_ids: tuple[str, ...] = Field(min_length=1)
    source_ids: tuple[str, ...] = Field(min_length=1)
    applicability: tuple[Text, ...] = Field(min_length=1)
    uncertainty: tuple[Text, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_stable_lineage(self):
        for name in ("record_ids", "source_ids", "applicability", "uncertainty"):
            values = getattr(self, name)
            if values != tuple(sorted(values)) or len(values) != len(set(values)):
                raise ValueError(f"{name} must use stable unique sorted order")
        return self


class EnrichmentMatrixCell(ImmutableModel):
    target: str
    semantic_state: RuntimeSemanticState
    provenance: RuntimeProvenance | None = None
    value: JsonValue = None
    confirmed: bool
    locked: bool
    source_ids: tuple[str, ...]
    applicable_policy_ids: tuple[str, ...] = ()


class EnrichmentProposal(ImmutableModel):
    target: str
    semantic_state: RuntimeSemanticState
    provenance: RuntimeProvenance
    value: JsonValue = None
    source_id: Text
    preservation: PreservationIntent = PreservationIntent.CHANGE

    @field_validator("source_id")
    @classmethod
    def validate_exact_source_id(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("enrichment proposal source_id must be exact")
        return value

    @model_validator(mode="after")
    def validate_authority(self):
        validate_proposal_authority(self.semantic_state, self.provenance)
        return self


class EnrichmentDecision(ImmutableModel):
    target: str
    outcome: Literal["APPLIED", "KEPT", "BLOCKED"]
    reason: str
    applicable_policy_ids: tuple[str, ...]
    proposal: EnrichmentProposal
    result: EnrichmentMatrixCell

    @model_validator(mode="after")
    def validate_target_lineage(self):
        if self.target != self.proposal.target or self.target != self.result.target:
            raise ValueError("enrichment decision target lineage mismatch")
        return self


class PromptEnrichmentResult(ImmutableModel):
    """Frozen historical 1.2 decoder; current writers emit StructuredPromptEnrichmentResult."""

    enrichment_version: Literal["1.2.0"] = "1.2.0"
    design_revision_id: str
    knowledge_package_id: str
    knowledge_artifact_version: str
    knowledge_runtime_sha256: str
    knowledge_validation_report_sha256: Sha256 | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    parametric_catalog_id: str | None = None
    parametric_artifact_version: str | None = None
    parametric_catalog_sha256: Sha256 | None = None
    parametric_references: tuple[ParametricEnrichmentReference, ...] = ()
    initial_matrix: tuple[EnrichmentMatrixCell, ...]
    decisions: tuple[EnrichmentDecision, ...]
    final_matrix: tuple[EnrichmentMatrixCell, ...]
    compiled_prompt: CompiledPrompt
    content_hash: str

    @model_validator(mode="after")
    def validate_hash(self):
        identity = (
            self.parametric_catalog_id,
            self.parametric_artifact_version,
            self.parametric_catalog_sha256,
        )
        if any(value is not None for value in identity) and not all(
            value is not None for value in identity
        ):
            raise ValueError("parametric catalog identity must be complete")
        if self.parametric_references and not all(value is not None for value in identity):
            raise ValueError("parametric references require catalog identity")
        keys = tuple(
            (
                item.target,
                item.material_id,
                item.shape_id,
                item.weight_ct,
                item.estimate_kind,
                item.dimensions.model_dump_json(),
                item.record_ids,
            )
            for item in self.parametric_references
        )
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("parametric references must use stable unique order")
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if self.content_hash != expected:
            raise ValueError("prompt enrichment content hash mismatch")
        return self


class StructuredPromptEnrichmentResult(ImmutableModel):
    """Current structured source, with no legacy text compiler dependency."""

    enrichment_version: Literal["1.3.0"] = PROMPT_ENRICHMENT_VERSION
    design_revision_id: str
    knowledge_package_id: str
    knowledge_artifact_version: str
    knowledge_runtime_sha256: str
    knowledge_validation_report_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    parametric_catalog_id: str | None = None
    parametric_artifact_version: str | None = None
    parametric_catalog_sha256: Sha256 | None = None
    parametric_references: tuple[ParametricEnrichmentReference, ...] = ()
    initial_matrix: tuple[EnrichmentMatrixCell, ...]
    decisions: tuple[EnrichmentDecision, ...]
    final_matrix: tuple[EnrichmentMatrixCell, ...]
    specification_entries: tuple[SpecificationEntry, ...]
    locked_constraints: tuple[PromptConstraint, ...]
    disclosures: tuple[PromptDisclosure, ...]
    prompt_template_artifact_version: Version
    content_hash: str

    @model_validator(mode="after")
    def validate_hash(self):
        # The canonical JSON hash and parametric metadata rules are deliberately shared.
        return PromptEnrichmentResult.validate_hash(self)


AnyPromptEnrichmentResult = Annotated[
    PromptEnrichmentResult | StructuredPromptEnrichmentResult,
    Field(discriminator="enrichment_version"),
]
_ENRICHMENT_DECODER = TypeAdapter(AnyPromptEnrichmentResult)


def decode_prompt_enrichment_result(value: object) -> AnyPromptEnrichmentResult:
    """Verify the ORIGINAL version/hash, including nested historical payloads; never rewrite."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return _ENRICHMENT_DECODER.validate_python(value)


def enrichment_projection(value: AnyPromptEnrichmentResult) -> RevisionProjection:
    result = decode_prompt_enrichment_result(value)
    source = result.compiled_prompt if isinstance(result, PromptEnrichmentResult) else result
    return RevisionProjection(
        specification_entries=source.specification_entries,
        locked_constraints=source.locked_constraints,
        disclosures=source.disclosures,
    )


def enrichment_template_version(value: AnyPromptEnrichmentResult) -> str:
    result = decode_prompt_enrichment_result(value)
    return (
        result.compiled_prompt.template_artifact_version
        if isinstance(result, PromptEnrichmentResult)
        else result.prompt_template_artifact_version
    )


def _cell(
    state: RuntimeParameterState,
    *,
    applicable_policy_ids: tuple[str, ...] = (),
) -> EnrichmentMatrixCell:
    return EnrichmentMatrixCell(
        target=state.target,
        semantic_state=state.semantic_state,
        provenance=state.provenance,
        value=state.model_dump(mode="json")["value"],
        confirmed=state.confirmed,
        locked=state.locked,
        source_ids=state.source_ids,
        applicable_policy_ids=applicable_policy_ids,
    )


def _matrix(
    state: KnowledgeRuntimeState,
    engine: KnowledgePolicyEngine,
) -> tuple[EnrichmentMatrixCell, ...]:
    return tuple(
        _cell(
            item,
            applicable_policy_ids=tuple(
                policy.policy_id
                for policy in engine.policies_for(
                    item.target,
                    existing_group_ids=state.existing_group_ids,
                )
            ),
        )
        for item in state.parameters
    )


def _is_authoritative_parametric_input(state: object | None) -> bool:
    if isinstance(state, Explicit):
        return True
    return isinstance(state, (Derived, Assumed)) and state.confirmed


def parametric_reference_context_is_eligible(revision: AnyDesignRevision | object) -> bool:
    """Return whether Product State can safely select center-stone size guidance.

    Explicit values are user authority even before a separate confirmation action. Derived and
    assumed values qualify only after confirmation. Existing or explicitly inapplicable dimensions
    always suppress advisory dimensional references.
    """

    revision = validate_design_revision(revision)
    stone = revision.design.center_stone
    if isinstance(stone.dimensions, (KnownValue, NotApplicable)):
        return False
    return all(
        _is_authoritative_parametric_input(state)
        for state in (stone.material, stone.shape, stone.weight)
    )


def enrich_prompt(
    revision: AnyDesignRevision | object,
    templates: PromptTemplateBundle,
    knowledge_runtime: AnyCompiledKnowledge,
    *,
    proposals: tuple[EnrichmentProposal, ...] = (),
    parametric_catalog_id: str | None = None,
    parametric_artifact_version: str | None = None,
    parametric_catalog_sha256: Sha256 | None = None,
    parametric_references: tuple[ParametricEnrichmentReference, ...] = (),
    template_id: str = "jewelry_visualization",
) -> StructuredPromptEnrichmentResult:
    """Evaluate proposals and project the canonical revision without compiling legacy text.

    Step 12 deliberately does not mutate DesignRevision. Matrix/policy results are structured
    derived output; the revision projection remains anchored to immutable canonical Product State.
    """
    revision = validate_design_revision(revision)
    templates = PromptTemplateBundle.model_validate(templates)
    runtime = validate_compiled_knowledge(knowledge_runtime)
    engine = KnowledgePolicyEngine(runtime)
    state = build_knowledge_runtime_state(runtime, revision)
    parametric_references = tuple(
        ParametricEnrichmentReference.model_validate(item) for item in parametric_references
    )
    if parametric_references and not parametric_reference_context_is_eligible(revision):
        raise ValueError(
            "parametric references require authoritative context and applicable unknown dimensions"
        )
    initial_matrix = _matrix(state, engine)

    decisions = []
    current = {item.target: item for item in state.parameters}
    for proposal in sorted(
        (EnrichmentProposal.model_validate(item) for item in proposals),
        key=lambda item: (item.target, item.source_id),
    ):
        evaluation = engine.evaluate_canonical(
            revision,
            RuntimeStateProposal(
                target=proposal.target,
                semantic_state=proposal.semantic_state,
                provenance=proposal.provenance,
                value=proposal.value,
                source_id=proposal.source_id,
                preservation=proposal.preservation,
            ),
            expected_revision_id=revision.revision_id,
            effective_state=KnowledgeRuntimeState(
                package_id=state.package_id,
                artifact_version=state.artifact_version,
                runtime_sha256=state.runtime_sha256,
                existing_group_ids=state.existing_group_ids,
                parameters=tuple(sorted(current.values(), key=lambda item: item.target)),
            ),
        )
        if evaluation.outcome == "APPLIED":
            current[proposal.target] = evaluation.result
        decisions.append(
            EnrichmentDecision(
                target=proposal.target,
                outcome=evaluation.outcome,
                reason=evaluation.reason,
                applicable_policy_ids=evaluation.applicable_policy_ids,
                proposal=proposal,
                result=_cell(
                    evaluation.result,
                    applicable_policy_ids=evaluation.applicable_policy_ids,
                ),
            )
        )

    final_state = KnowledgeRuntimeState(
        package_id=state.package_id,
        artifact_version=state.artifact_version,
        runtime_sha256=state.runtime_sha256,
        existing_group_ids=state.existing_group_ids,
        parameters=tuple(sorted(current.values(), key=lambda item: item.target)),
    )
    final_matrix = _matrix(final_state, engine)
    # Preserve the existing template identity check, but do not compile text.
    if template_id not in {item.template_id for item in templates.templates}:
        raise KeyError("Unknown prompt template ID")
    projection = project_revision(revision)
    payload = {
        "enrichment_version": PROMPT_ENRICHMENT_VERSION,
        "design_revision_id": str(revision.revision_id),
        "knowledge_package_id": runtime.package_id,
        "knowledge_artifact_version": runtime.artifact_version,
        "knowledge_runtime_sha256": runtime.sha256,
        "parametric_catalog_id": parametric_catalog_id,
        "parametric_artifact_version": parametric_artifact_version,
        "parametric_catalog_sha256": parametric_catalog_sha256,
        "parametric_references": [item.model_dump(mode="json") for item in parametric_references],
        "initial_matrix": [item.model_dump(mode="json") for item in initial_matrix],
        "decisions": [item.model_dump(mode="json") for item in decisions],
        "final_matrix": [item.model_dump(mode="json") for item in final_matrix],
        **projection.model_dump(mode="json"),
        "prompt_template_artifact_version": templates.artifact_version,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return StructuredPromptEnrichmentResult(
        **payload,
        content_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def enrich_prompt_with_active_release(
    revision: AnyDesignRevision | object,
    templates: PromptTemplateBundle,
    artifact_store: AnyKnowledgeStore,
    *,
    knowledge_package_id: str,
    knowledge_artifact_version: str,
    active_release: AnyActiveKnowledge | object,
    validation_report: AnyValidationReport | object,
    proposals: tuple[EnrichmentProposal, ...] = (),
    parametric_catalog_id: str | None = None,
    parametric_artifact_version: str | None = None,
    parametric_catalog_sha256: Sha256 | None = None,
    parametric_references: tuple[ParametricEnrichmentReference, ...] = (),
    template_id: str = "jewelry_visualization",
) -> StructuredPromptEnrichmentResult:
    """Enrich one cycle with an explicitly selected, durably verified ACTIVE release."""

    verified = artifact_store.load_active_runtime(
        knowledge_package_id,
        knowledge_artifact_version,
        active_release=active_release,
        validation_report=validation_report,
    )
    base = enrich_prompt(
        revision,
        templates,
        verified.compiled_runtime,
        proposals=proposals,
        parametric_catalog_id=parametric_catalog_id,
        parametric_artifact_version=parametric_artifact_version,
        parametric_catalog_sha256=parametric_catalog_sha256,
        parametric_references=parametric_references,
        template_id=template_id,
    )
    payload = base.model_dump(mode="json", exclude={"content_hash"})
    payload["knowledge_validation_report_sha256"] = verified.validation_report_sha256
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return StructuredPromptEnrichmentResult(
        **payload,
        content_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )
