"""Prompt Enrichment entry points for Knowledge Library Contract v1.1.0."""

import hashlib
import json

from jewelai_domain.knowledge_activation_v1_1 import (
    ActiveKnowledgeRuntimeV1_1,
    ProductionValidationReportV1_1,
    Sha256,
)
from jewelai_domain.knowledge_library_v1_1 import CompiledKnowledgeLibraryV1_1
from jewelai_domain.knowledge_policy import (
    KnowledgeRuntimeState,
    RuntimeStateProposal,
)
from jewelai_domain.knowledge_policy_v1_1 import (
    KnowledgePolicyEngineV1_1,
    build_knowledge_runtime_state_v1_1,
)
from jewelai_domain.knowledge_storage_v1_1 import KnowledgeArtifactStoreV1_1
from jewelai_domain.models_v1_1 import AnyDesignRevision, validate_design_revision

from .compiler import compile_prompt
from .enrichment import (
    PROMPT_ENRICHMENT_VERSION,
    EnrichmentDecision,
    EnrichmentProposal,
    ParametricEnrichmentReference,
    PromptEnrichmentResult,
    _cell,
    _matrix,
    parametric_reference_context_is_eligible,
)
from .models import PromptTemplateBundle


def enrich_prompt_v1_1(
    revision: AnyDesignRevision | object,
    templates: PromptTemplateBundle,
    knowledge_runtime: CompiledKnowledgeLibraryV1_1 | object,
    *,
    proposals: tuple[EnrichmentProposal, ...] = (),
    parametric_catalog_id: str | None = None,
    parametric_artifact_version: str | None = None,
    parametric_catalog_sha256: Sha256 | None = None,
    parametric_references: tuple[ParametricEnrichmentReference, ...] = (),
    template_id: str = "jewelry_visualization",
) -> PromptEnrichmentResult:
    revision = validate_design_revision(revision)
    templates = PromptTemplateBundle.model_validate(templates)
    runtime = CompiledKnowledgeLibraryV1_1.model_validate(knowledge_runtime)
    engine = KnowledgePolicyEngineV1_1(runtime)
    state = build_knowledge_runtime_state_v1_1(runtime, revision)
    parametric_references = tuple(
        ParametricEnrichmentReference.model_validate(item)
        for item in parametric_references
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
        evaluation = engine.evaluate(
            KnowledgeRuntimeState(
                package_id=state.package_id,
                artifact_version=state.artifact_version,
                runtime_sha256=state.runtime_sha256,
                existing_group_ids=state.existing_group_ids,
                parameters=tuple(
                    sorted(current.values(), key=lambda item: item.target)
                ),
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
        "knowledge_artifact_version": str(runtime.artifact_version),
        "knowledge_runtime_sha256": runtime.sha256,
        "parametric_catalog_id": parametric_catalog_id,
        "parametric_artifact_version": parametric_artifact_version,
        "parametric_catalog_sha256": parametric_catalog_sha256,
        "parametric_references": [
            item.model_dump(mode="json") for item in parametric_references
        ],
        "initial_matrix": [item.model_dump(mode="json") for item in initial_matrix],
        "decisions": [item.model_dump(mode="json") for item in decisions],
        "final_matrix": [item.model_dump(mode="json") for item in final_matrix],
        "compiled_prompt": compiled.model_dump(mode="json"),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return PromptEnrichmentResult(
        **payload,
        content_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def enrich_prompt_with_active_release_v1_1(
    revision: AnyDesignRevision | object,
    templates: PromptTemplateBundle,
    artifact_store: KnowledgeArtifactStoreV1_1,
    *,
    knowledge_package_id: str,
    knowledge_artifact_version: str,
    active_release: ActiveKnowledgeRuntimeV1_1 | object,
    validation_report: ProductionValidationReportV1_1 | object,
    proposals: tuple[EnrichmentProposal, ...] = (),
    parametric_catalog_id: str | None = None,
    parametric_artifact_version: str | None = None,
    parametric_catalog_sha256: Sha256 | None = None,
    parametric_references: tuple[ParametricEnrichmentReference, ...] = (),
    template_id: str = "jewelry_visualization",
) -> PromptEnrichmentResult:
    verified = artifact_store.load_active_runtime(
        knowledge_package_id,
        knowledge_artifact_version,
        active_release=active_release,
        validation_report=validation_report,
    )
    base = enrich_prompt_v1_1(
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
    payload["knowledge_validation_report_sha256"] = (
        verified.validation_report_sha256
    )
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return PromptEnrichmentResult(
        **payload,
        content_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )
