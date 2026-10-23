"""Deterministic Knowledge Library enrichment matrix for prompt compilation."""

import hashlib
import json
from typing import Literal

from jewelai_domain.knowledge_activation import (
    ActiveKnowledgeRuntime,
    ProductionValidationReport,
    Sha256,
)
from jewelai_domain.knowledge_library import CompiledKnowledgeLibrary
from jewelai_domain.knowledge_policy import (
    KnowledgePolicyEngine,
    KnowledgeRuntimeState,
    PreservationIntent,
    RuntimeParameterState,
    RuntimeProvenance,
    RuntimeSemanticState,
    RuntimeStateProposal,
    build_knowledge_runtime_state,
)
from jewelai_domain.knowledge_storage import KnowledgeArtifactStore
from jewelai_domain.models import DesignRevision, ImmutableModel, Text
from pydantic import Field, JsonValue, field_validator, model_validator

from .compiler import compile_prompt
from .models import CompiledPrompt, PromptTemplateBundle

PROMPT_ENRICHMENT_VERSION = "1.1.0"


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
    enrichment_version: Literal["1.1.0"] = PROMPT_ENRICHMENT_VERSION
    design_revision_id: str
    knowledge_package_id: str
    knowledge_artifact_version: str
    knowledge_runtime_sha256: str
    knowledge_validation_report_sha256: Sha256 | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    initial_matrix: tuple[EnrichmentMatrixCell, ...]
    decisions: tuple[EnrichmentDecision, ...]
    final_matrix: tuple[EnrichmentMatrixCell, ...]
    compiled_prompt: CompiledPrompt
    content_hash: str

    @model_validator(mode="after")
    def validate_hash(self):
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if self.content_hash != expected:
            raise ValueError("prompt enrichment content hash mismatch")
        return self


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


def enrich_prompt(
    revision: DesignRevision,
    templates: PromptTemplateBundle,
    knowledge_runtime: CompiledKnowledgeLibrary,
    *,
    proposals: tuple[EnrichmentProposal, ...] = (),
    template_id: str = "jewelry_visualization",
) -> PromptEnrichmentResult:
    """Evaluate deterministic enrichment proposals before compiling the canonical prompt.

    Step 12 deliberately does not mutate DesignRevision. Matrix/policy results are structured
    derived output, while Prompt Compiler remains anchored to the immutable canonical revision.
    """
    revision = DesignRevision.model_validate(revision)
    templates = PromptTemplateBundle.model_validate(templates)
    runtime = CompiledKnowledgeLibrary.model_validate(knowledge_runtime)
    engine = KnowledgePolicyEngine(runtime)
    state = build_knowledge_runtime_state(runtime, revision)
    initial_matrix = _matrix(state, engine)

    decisions = []
    current = {item.target: item for item in state.parameters}
    for proposal in sorted(
        (EnrichmentProposal.model_validate(item) for item in proposals),
        key=lambda item: (item.target, item.source_id),
    ):
        evaluation = engine.evaluate(
            KnowledgeRuntimeState(
                package_id=state.package_id,
                artifact_version=state.artifact_version,
                runtime_sha256=state.runtime_sha256,
                existing_group_ids=state.existing_group_ids,
                parameters=tuple(sorted(current.values(), key=lambda item: item.target)),
            ),
            RuntimeStateProposal(
                target=proposal.target,
                semantic_state=proposal.semantic_state,
                provenance=proposal.provenance,
                value=proposal.value,
                source_id=proposal.source_id,
                preservation=proposal.preservation,
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
    compiled = compile_prompt(revision, templates, template_id=template_id)
    payload = {
        "enrichment_version": PROMPT_ENRICHMENT_VERSION,
        "design_revision_id": str(revision.revision_id),
        "knowledge_package_id": runtime.package_id,
        "knowledge_artifact_version": runtime.artifact_version,
        "knowledge_runtime_sha256": runtime.sha256,
        "initial_matrix": [item.model_dump(mode="json") for item in initial_matrix],
        "decisions": [item.model_dump(mode="json") for item in decisions],
        "final_matrix": [item.model_dump(mode="json") for item in final_matrix],
        "compiled_prompt": compiled.model_dump(mode="json"),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return PromptEnrichmentResult(
        **payload,
        content_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def enrich_prompt_with_active_release(
    revision: DesignRevision,
    templates: PromptTemplateBundle,
    artifact_store: KnowledgeArtifactStore,
    *,
    knowledge_package_id: str,
    knowledge_artifact_version: str,
    active_release: ActiveKnowledgeRuntime | object,
    validation_report: ProductionValidationReport | object,
    proposals: tuple[EnrichmentProposal, ...] = (),
    template_id: str = "jewelry_visualization",
) -> PromptEnrichmentResult:
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
        template_id=template_id,
    )
    payload = base.model_dump(mode="json", exclude={"content_hash"})
    payload["knowledge_validation_report_sha256"] = verified.validation_report_sha256
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return PromptEnrichmentResult(
        **payload,
        content_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )
