"""Explicit F06 output builders. No default upgrade, persistence or provider calls.

The input is the unchanged F05 source-verified snapshot. Only presentation and
family hash domains differ; authority/readiness remain the existing projections.
"""

import json
from types import SimpleNamespace
from typing import Literal

from jewelai_domain.preservation import contract_hash
from pydantic import model_validator

from .downstream_preparation import check_ifp_v2_1_capacity, render_canonical_source_text
from .enrichment import enrichment_projection
from .final_prompt import (
    FinalPromptReadiness,
    _design_facts,
    _enrichment_evidence,
    _render_internal_prompt,
    _validate_snapshot,
)
from .final_prompt_v3 import f04_semantic_components
from .final_prompt_v4 import (
    CanonicalFinalPromptAssemblyV4,
    CanonicalInternalFinalPromptHandoffV4,
    CanonicalInternalFinalPromptV4,
    FinalPromptSnapshotV3,
    UserReadableJewelryDescriptionV3,
    current_constraints,
    legacy_current_semantics,
)
from .review_description import render_review_description


class UserReadableJewelryDescriptionV4(UserReadableJewelryDescriptionV3):
    schema_version: Literal["4.0.0"]

    @model_validator(mode="after")
    def validate_hash(self):
        if self.content_hash != contract_hash(
            "jewelai.UserReadableJewelryDescription/4.0.0",
            self.model_dump(mode="json", exclude={"content_hash"}),
        ):
            raise ValueError("Description4 integrity mismatch")
        if self.authoritative_revision_id != self.current_frame.revision_id:
            raise ValueError("Description4 revision/frame mismatch")
        return self


class CanonicalInternalFinalPromptV5(CanonicalInternalFinalPromptV4):
    schema_version: Literal["5.0.0"]
    description: UserReadableJewelryDescriptionV4

    @model_validator(mode="after")
    def validate_hash(self):
        if self.content_hash != contract_hash(
            "jewelai.InternalFinalPrompt/5.0.0",
            self.model_dump(mode="json", exclude={"content_hash"}),
        ):
            raise ValueError("IFP5 integrity mismatch")
        return self


class CanonicalFinalPromptAssemblyV5(CanonicalFinalPromptAssemblyV4):
    description: UserReadableJewelryDescriptionV4
    internal_final_prompt: CanonicalInternalFinalPromptV5


class CanonicalInternalFinalPromptHandoffV5(CanonicalInternalFinalPromptHandoffV4):
    schema_version: Literal["5.0.0"]
    internal_final_prompt_schema_version: Literal["5.0.0"]
    internal_final_prompt: CanonicalInternalFinalPromptV5

    @model_validator(mode="after")
    def validate_authoritative_binding(self):
        prompt = self.internal_final_prompt
        if (
            self.organization_id != prompt.organization_id
            or self.session_id != prompt.session_id
            or self.product_state_revision_id != prompt.product_state_revision_id
            or self.enrichment_cycle_id != prompt.enrichment_cycle_id
            or self.knowledge_release != prompt.knowledge_release
            or self.internal_final_prompt_schema_version != prompt.schema_version
            or self.internal_final_prompt_content_hash != prompt.content_hash
            or self.readiness != prompt.readiness
            or self.ready_for_downstream_preparation
            != (
                prompt.readiness
                in {FinalPromptReadiness.READY, FinalPromptReadiness.READY_WITH_UNRESOLVED}
            )
        ):
            raise ValueError("Handoff5 authoritative source binding mismatch")
        if self.content_hash != contract_hash(
            "jewelai.InternalFinalPromptHandoff/5.0.0",
            self.model_dump(mode="json", exclude={"content_hash"}),
        ):
            raise ValueError("Handoff5 integrity mismatch")
        return self


def assemble_internal_final_prompt_v5(
    snapshot, *, dictionary, templates, _pending_descriptions=(), _source_facts=None
):
    """Explicit internal opt-in only; no replacement of any historical artifact.

    Supply the existing source-verified F05 snapshot from one scoped read frame.
    Calling this builder is not authorization, persistence, a runtime default or
    permission to send version 5 to a downstream consumer.
    """
    # Revalidate JSON as well as the original type, including unchecked model_copy.
    if hasattr(snapshot, "model_dump"):
        snapshot = snapshot.model_dump(mode="json")
    snapshot = FinalPromptSnapshotV3.model_validate_json(json.dumps(snapshot))
    _validate_snapshot(snapshot, dictionary=dictionary, templates=templates)
    facts = _design_facts(snapshot)
    constraints = current_constraints(snapshot, facts)
    if snapshot.retained_base == "F":
        native = snapshot.enrichment_result
        if getattr(native, "enrichment_version", None) == "3.0.0":
            native = native.native
        view = SimpleNamespace(
            **{
                name: getattr(snapshot, name)
                for name in type(snapshot).model_fields
                if name != "enrichment_result"
            },
            enrichment_result=native,
            effective_unresolved_frontier=snapshot.native_frontier,
        )
        unresolved, _, readiness = f04_semantic_components(view, facts, _source_facts=_source_facts)
        reason = snapshot.rule_decision.reason
    else:
        unresolved, readiness, reason = legacy_current_semantics(snapshot)
    if len(_pending_descriptions) != len(snapshot.protection_projection.pending_requests):
        raise ValueError("Pending output requires every actual sourced logical request")
    if snapshot.protection_projection.pending_requests:
        readiness, reason = (
            FinalPromptReadiness.BLOCKED,
            "Explicit scoped KEEP confirmation is required.",
        )
    rendered = render_review_description(
        snapshot,
        facts,
        constraints,
        unresolved,
        dictionary=dictionary,
        pending=_pending_descriptions,
    )
    description_payload = dict(
        schema_version="4.0.0",
        locale=snapshot.locale,
        authoritative_revision_id=snapshot.revision.revision_id,
        text=rendered.text,
        unresolved_summary=rendered.unresolved_summary,
        current_frame=snapshot.current_frame,
        protection_projection_hash=snapshot.protection_projection.content_hash,
        compatibility_projection_hash=snapshot.compatibility_projection.content_hash
        if snapshot.compatibility_projection
        else None,
        sealed_frontier_hash=snapshot.native_frontier.content_hash
        if snapshot.native_frontier
        else None,
    )
    description = UserReadableJewelryDescriptionV4(
        **description_payload,
        content_hash=contract_hash(
            "jewelai.UserReadableJewelryDescription/4.0.0", description_payload
        ),
    )
    text = _render_internal_prompt(
        description,
        facts,
        constraints,
        unresolved,
        readiness,
        snapshot.enrichment_result.parametric_references,
    )
    check_ifp_v2_1_capacity(text)
    payload = dict(
        schema_version="5.0.0",
        session_id=snapshot.session_id,
        organization_id=snapshot.organization_id,
        design_id=snapshot.revision.design_id,
        product_state_revision_id=snapshot.revision.revision_id,
        enrichment_cycle_id=snapshot.enrichment_cycle_id,
        enrichment_cycle_number=snapshot.enrichment_cycle_number,
        locale=snapshot.locale,
        readiness=readiness,
        readiness_reason=reason,
        description_content_hash=description.content_hash,
        description=description,
        prompt_text="JEWELAI INTERNAL FINAL PROMPT 5.0.0\n" + text.split("\n", 1)[1],
        design_facts=facts,
        constraints=constraints,
        unresolved_details=unresolved,
        enrichment_evidence=_enrichment_evidence(snapshot, facts),
        decision_lineage=snapshot.decision_lineage,
        constraint_evidence=snapshot.constraint_evidence,
        knowledge_release=snapshot.knowledge_release,
        artifact_versions=snapshot.artifact_versions,
        enrichment_result_content_hash=snapshot.enrichment_result.content_hash,
        parametric_references=snapshot.enrichment_result.parametric_references,
        disclosures=enrichment_projection(snapshot.enrichment_result).disclosures,
        retained_base=snapshot.retained_base,
        extension_profile=snapshot.extension_profile,
        current_frame=snapshot.current_frame,
        protection_projection=snapshot.protection_projection,
        compatibility_projection=snapshot.compatibility_projection,
        native_frontier=snapshot.native_frontier,
        native_availability_overlay=(
            snapshot.enrichment_result.availability_overlay
            if snapshot.retained_base == "F"
            else None
        ),
        cause_definitions=snapshot.cause_definitions,
    )
    source = CanonicalInternalFinalPromptV5(
        **payload, content_hash=contract_hash("jewelai.InternalFinalPrompt/5.0.0", payload)
    )
    if source.prompt_text != render_canonical_source_text(source):
        raise ValueError("IFP5 canonical source text mismatch")
    return CanonicalFinalPromptAssemblyV5(description=description, internal_final_prompt=source)
