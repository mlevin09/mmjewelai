"""F05 read-only current outputs. Frozen L/F output contracts remain unchanged.

The caller must supply source-verified native history under one scoped read
frame. This module never admits a continuation or accepts a preservation release.
"""

from typing import Literal

from jewelai_domain.clarification_state import (
    CanonicalAvailabilityOverlay,
    CauseDefinition,
    EffectiveUnresolvedFrontier,
    Sha256,
    StrictEvidenceModel,
    evidence_hash,
)
from jewelai_domain.compatibility import CompatibilityReadinessProjection
from jewelai_domain.continuation import ContinuationFrame
from jewelai_domain.preservation import (
    ProtectionProjection,
    anchor_hash,
    contract_hash,
    protected_targets,
    target_state,
)
from jewelai_domain.rules import BlockDecision, ReadyDecision, RuleDecision
from jewelai_domain.rules_v2 import RuleDecisionV2
from pydantic import ValidationError, model_validator

from .continuation import ContinuationEnrichmentResult
from .downstream_preparation import (
    RENDER_MAX_CHARACTERS,
    CanonicalInternalFinalPromptV2_1,
    GenerationPreparationError,
    PreparationErrorCode,
    check_ifp_v2_1_capacity,
    render_canonical_source_text,
)
from .enrichment import (
    StructuredPromptEnrichmentResult,
    StructuredPromptEnrichmentResultV2,
    enrichment_projection,
)
from .final_prompt import (
    FinalPromptAssembly,
    FinalPromptConstraint,
    FinalPromptReadiness,
    FinalPromptSnapshot,
    FinalPromptUnresolvedDetail,
    UserReadableJewelryDescription,
    _check_current_text_capacity,
    _constraints,
    _description,
    _design_facts,
    _enrichment_evidence,
    _render_internal_prompt,
    _unresolved_details,
    _validate_snapshot,
)
from .final_prompt_v3 import (
    FinalPromptUnresolvedDetailV3,
    f04_current_components,
)
from .handoff import InternalFinalPromptHandoff


def _validate_root_evidence(protection, evidence):
    expected = {
        e.evidence_id: e
        for e in evidence
        if e.status == "active"
        and e.kind == "preservation"
        and e.semantic_subject == "component.center_stone"
    }
    roots = {r.root_ref.evidence_id: r for r in protection.roots}
    if set(expected) != set(roots):
        raise ValueError("Current protection has missing or unbacked source roots")
    for key, root in roots.items():
        source = expected[key]
        if (
            root.root_ref.content_hash != source.content_hash
            or root.root_ref.source_revision_id != source.source_revision_id
            or root.source_revision_id != source.source_revision_id
            or root.root_ref.source_cycle_id != source.source_enrichment_cycle_id
        ):
            raise ValueError("Current protection root/source evidence mismatch")


class FinalPromptSnapshotV3(FinalPromptSnapshot, StrictEvidenceModel):
    def _coexisting_preservation(self, item):
        if not (item.kind == "preservation" and item.semantic_subject == "component.center_stone"):
            return False
        protected = {r.root_ref.evidence_id for r in self.protection_projection.roots}
        return all(
            e.evidence_id in protected
            for e in self.constraint_evidence
            if e.status == "active" and e.semantic_subject == item.semantic_subject
        )

    schema_version: Literal["3.0.0"]
    retained_base: Literal["L", "F"]
    extension_profile: Literal["jewelai.prompt-enrichment.f05/1.0.0"] | None
    current_frame: ContinuationFrame
    enrichment_result: (
        StructuredPromptEnrichmentResult
        | StructuredPromptEnrichmentResultV2
        | ContinuationEnrichmentResult
    )
    rule_decision: RuleDecisionV2 | RuleDecision
    protection_projection: ProtectionProjection
    compatibility_projection: CompatibilityReadinessProjection | None
    native_frontier: EffectiveUnresolvedFrontier | None
    cause_definitions: tuple[CauseDefinition, ...]

    @model_validator(mode="after")
    def validate_current_binding(self):
        frame, protection = self.current_frame, self.protection_projection
        _validate_root_evidence(protection, self.constraint_evidence)
        if (
            protection.scope.session_id != self.session_id
            or protection.scope.organization_id != self.organization_id
            or protection.scope.design_id != self.revision.design_id
            or protection.current_revision_id != self.revision.revision_id
            or protection.current_revision_sha256 != evidence_hash(self.revision)
            or frame.revision_id != self.revision.revision_id
            or frame.revision_sha256 != evidence_hash(self.revision)
            or frame.enrichment_cycle_id != self.enrichment_cycle_id
            or frame.enrichment_cycle_number != self.enrichment_cycle_number
            or frame.enrichment_result_hash != self.enrichment_result.content_hash
        ):
            raise ValueError("F05 output does not describe one current scoped frame")
        for anchor in protection.anchors:
            if anchor.baseline_state_sha256 != anchor_hash(
                target_state(self.revision.design, anchor.target.concrete_target)
            ):
                raise ValueError("Current protection anchor contradicts canonical state")
        if self.retained_base == "L":
            compat = self.compatibility_projection
            if (
                self.native_frontier is not None
                or self.cause_definitions
                or compat is None
                or compat.scope != protection.scope
                or compat.evidence_head != frame
                or compat.current_frame_core.model_dump()
                != frame.model_dump(exclude={"plan_hash", "history_root_sha256"})
                or (
                    self.extension_profile is None
                    and compat.legacy_history_root_sha256 != frame.history_root_sha256
                )
                or self.artifact_versions.question_artifact_version != "1.0.0"
                or self.artifact_versions.rules_artifact_version != "1.0.0"
                or self.enrichment_result.enrichment_version not in {"1.3.0", "3.0.0"}
            ):
                raise ValueError("L current output has incompatible native/projection evidence")
            historical = {
                (d.kind, d.decision_id, d.content_hash)
                for d in self.decision_lineage
                if d.blocks_progression
            }
            if not {(d.kind, d.id, d.hash) for d in compat.remaining_blocker_refs}.issubset(
                historical
            ):
                raise ValueError("Compatibility references an unknown historical blocker")
        else:
            frontier = self.native_frontier
            if (
                self.compatibility_projection is not None
                or frontier is None
                or frontier.frontier_core.scope != protection.scope
                or frontier.frontier_core.current_revision_id != frame.revision_id
                or frontier.frontier_core.revision_sha256 != frame.revision_sha256
                or frontier.current_plan_ref.plan_id != frame.plan_id
                or frontier.current_plan_ref.content_hash != frame.plan_hash
            ):
                raise ValueError("F current output has incompatible native frontier")
        return self


class UserReadableJewelryDescriptionV3(UserReadableJewelryDescription, StrictEvidenceModel):
    schema_version: Literal["3.0.0"]
    current_frame: ContinuationFrame
    protection_projection_hash: Sha256
    compatibility_projection_hash: Sha256 | None
    sealed_frontier_hash: Sha256 | None

    @model_validator(mode="after")
    def validate_hash(self):
        if self.content_hash != contract_hash(
            "jewelai.UserReadableJewelryDescription/3.0.0",
            self.model_dump(mode="json", exclude={"content_hash"}),
        ):
            raise ValueError("Description3 integrity mismatch")
        if self.authoritative_revision_id != self.current_frame.revision_id:
            raise ValueError("Description3 revision/frame mismatch")
        return self


class CanonicalInternalFinalPromptV4(CanonicalInternalFinalPromptV2_1, StrictEvidenceModel):
    schema_version: Literal["4.0.0"]
    description: UserReadableJewelryDescriptionV3
    retained_base: Literal["L", "F"]
    extension_profile: Literal["jewelai.prompt-enrichment.f05/1.0.0"] | None
    current_frame: ContinuationFrame
    protection_projection: ProtectionProjection
    compatibility_projection: CompatibilityReadinessProjection | None
    native_frontier: EffectiveUnresolvedFrontier | None
    native_availability_overlay: CanonicalAvailabilityOverlay | None
    cause_definitions: tuple[CauseDefinition, ...]
    unresolved_details: tuple[FinalPromptUnresolvedDetailV3 | FinalPromptUnresolvedDetail, ...]

    @model_validator(mode="after")
    def validate_hash(self):
        if self.content_hash != contract_hash(
            "jewelai.InternalFinalPrompt/4.0.0",
            self.model_dump(mode="json", exclude={"content_hash"}),
        ):
            raise ValueError("IFP4 integrity mismatch")
        return self

    @model_validator(mode="after")
    def validate_current_evidence(self):
        frame, protection, description = (
            self.current_frame,
            self.protection_projection,
            self.description,
        )
        compat, frontier = self.compatibility_projection, self.native_frontier
        _validate_root_evidence(protection, self.constraint_evidence)
        if (
            frame.revision_id != self.product_state_revision_id
            or frame.enrichment_cycle_id != self.enrichment_cycle_id
            or frame.enrichment_cycle_number != self.enrichment_cycle_number
            or frame.enrichment_result_hash != self.enrichment_result_content_hash
            or description.current_frame != frame
            or description.protection_projection_hash != protection.content_hash
            or description.compatibility_projection_hash
            != (compat.content_hash if compat else None)
            or description.sealed_frontier_hash != (frontier.content_hash if frontier else None)
            or protection.scope.session_id != self.session_id
            or protection.scope.organization_id != self.organization_id
            or protection.scope.design_id != self.design_id
            or protection.current_revision_id != frame.revision_id
            or protection.current_revision_sha256 != frame.revision_sha256
            or protection.design_schema_version != self.artifact_versions.design_schema_version
            or (
                self.artifact_versions.question_artifact_version,
                self.artifact_versions.rules_artifact_version,
            )
            != (("1.0.0", "1.0.0") if self.retained_base == "L" else ("2.0.0", "2.0.0"))
        ):
            raise ValueError("IFP4 evidence/frame/description mismatch")
        if self.retained_base == "L":
            if (
                compat is None
                or frontier is not None
                or compat.evidence_head != frame
                or compat.scope != protection.scope
                or compat.current_frame_core.model_dump()
                != frame.model_dump(exclude={"plan_hash", "history_root_sha256"})
                or (
                    self.extension_profile is None
                    and compat.legacy_history_root_sha256 != frame.history_root_sha256
                )
                or self.native_availability_overlay is not None
                or self.cause_definitions
            ):
                raise ValueError("IFP4 L evidence mismatch")
            blocked = bool(compat.remaining_blocker_refs)
        else:
            if (
                compat is not None
                or frontier is None
                or frontier.current_plan_ref.plan_id != frame.plan_id
                or frontier.current_plan_ref.content_hash != frame.plan_hash
                or frontier.frontier_core.scope != protection.scope
                or frontier.frontier_core.current_revision_id != frame.revision_id
                or frontier.frontier_core.revision_sha256 != frame.revision_sha256
                or self.native_availability_overlay is None
                or self.native_availability_overlay.scope != protection.scope
                or self.native_availability_overlay.canonical_revision_id != frame.revision_id
                or self.native_availability_overlay.canonical_revision_sha256
                != frame.revision_sha256
                or self.native_availability_overlay.design_schema_version
                != protection.design_schema_version
            ):
                raise ValueError("IFP4 F evidence mismatch")
            states = {c.cause_id: c for c in frontier.frontier_core.cause_states}
            definitions = {c.cause_id: c for c in self.cause_definitions}
            if (
                len(definitions) != len(self.cause_definitions)
                or set(states) != set(definitions)
                or any(c.scope != protection.scope for c in definitions.values())
            ):
                raise ValueError("IFP4 native cause definition mismatch")
            current = {key: c for key, c in states.items() if c.status == "OPEN"}
            if (
                len(current) != len(self.unresolved_details)
                or any(
                    not isinstance(d, FinalPromptUnresolvedDetailV3)
                    for d in self.unresolved_details
                )
                or {d.cause_id for d in self.unresolved_details} != set(current)
            ):
                raise ValueError("IFP4 native unresolved evidence mismatch")
            for detail in self.unresolved_details:
                state = current[detail.cause_id]
                if (
                    detail.blocking != state.blocks_current
                    or detail.criticality != state.criticality
                    or detail.owner != state.availability_target_ref
                ):
                    raise ValueError("IFP4 native unresolved owner/criticality mismatch")
            blocked = any(c.blocks_current for c in frontier.frontier_core.cause_states)
        if (
            blocked or protection.pending_requests
        ) and self.readiness != FinalPromptReadiness.BLOCKED:
            raise ValueError("IFP4 readiness bypasses current unresolved evidence")
        return self


class CanonicalFinalPromptAssemblyV4(FinalPromptAssembly, StrictEvidenceModel):
    description: UserReadableJewelryDescriptionV3
    internal_final_prompt: CanonicalInternalFinalPromptV4


class CanonicalInternalFinalPromptHandoffV4(InternalFinalPromptHandoff, StrictEvidenceModel):
    schema_version: Literal["4.0.0"]
    internal_final_prompt_schema_version: Literal["4.0.0"]
    internal_final_prompt: CanonicalInternalFinalPromptV4

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
            raise ValueError("Handoff4 authoritative source binding mismatch")
        if self.content_hash != contract_hash(
            "jewelai.InternalFinalPromptHandoff/4.0.0",
            self.model_dump(mode="json", exclude={"content_hash"}),
        ):
            raise ValueError("Handoff4 integrity mismatch")
        return self


def current_constraints(snapshot, facts):
    """Coalesce active KEEP roots, keeping LOCK and original evidence independently."""
    projection = snapshot.protection_projection
    roots = {r.root_ref.evidence_id: r for r in projection.roots}
    root_ids = set(roots)
    constraints = [
        c
        for c in _constraints(snapshot, facts)
        if not (c.kind == "preservation" and root_ids.intersection(c.source_ids))
    ]
    targets = {t.concrete_target for r in roots.values() for t in r.scope_targets}
    if not targets:
        return tuple(constraints)
    whole = targets == set(protected_targets(snapshot.revision.schema_version))
    scopes = ("component.center_stone",) if whole else tuple(sorted(targets))
    for target in scopes:
        included = tuple(
            sorted(
                r.root_ref.evidence_id
                for r in roots.values()
                if whole or any(t.concrete_target == target for t in r.scope_targets)
            )
        )
        constraints.append(
            FinalPromptConstraint(
                kind="preservation",
                target=target,
                instruction=(
                    "Keep the current center stone unchanged."
                    if whole and snapshot.locale == "en"
                    else "Сохранить текущий центральный камень без изменений."
                    if whole
                    else "Keep this current authoritative center-stone field unchanged."
                    if snapshot.locale == "en"
                    else "Сохранить текущее авторитетное значение поля центрального камня."
                ),
                source_ids=included,
            )
        )
    return tuple(sorted(constraints, key=lambda c: (c.target, c.kind, c.source_ids)))


def _current_f_components(*args, **kwargs):
    """Map only freshly rendered F description overflow to F05's capacity error.

    The frozen F renderer constructs its bounded Description2 before F05 can
    check Description3. Preserve every other integrity/validation failure and
    the historical F entry point; never serialize the rejected source text.
    """
    try:
        return f04_current_components(*args, **kwargs)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_url=False)
        if (
            exc.title == "UserReadableJewelryDescriptionV2"
            and len(errors) == 1
            and errors[0]["type"] == "string_too_long"
            and errors[0]["loc"] == ("text",)
            and errors[0].get("ctx", {}).get("max_length") == RENDER_MAX_CHARACTERS
        ):
            raise GenerationPreparationError(PreparationErrorCode.CAPACITY) from None
        raise


def assemble_internal_final_prompt_v4(
    snapshot, *, dictionary, templates, _pending_descriptions=(), _source_facts=None
):
    snapshot = FinalPromptSnapshotV3.model_validate(snapshot)
    _validate_snapshot(snapshot, dictionary=dictionary, templates=templates)
    facts = _design_facts(snapshot)
    constraints = current_constraints(snapshot, facts)
    if snapshot.retained_base == "F":
        from types import SimpleNamespace

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
        base_description, unresolved, readiness = _current_f_components(
            view, dictionary, facts, constraints, _source_facts=_source_facts
        )
        reason = snapshot.rule_decision.reason
    else:
        compat = snapshot.compatibility_projection
        discharged_hashes = {
            p.original_answer_ref.hash
            for p in compat.proofs
            if p.kind == "accepted_target_replaces_unknown"
        }
        discharged = {
            d.decision_id
            for d in snapshot.decision_lineage
            if d.kind == "clarification" and d.content_hash in discharged_hashes
        }
        unresolved = tuple(
            d for d in _unresolved_details(snapshot) if not discharged.intersection(d.source_ids)
        )
        if isinstance(snapshot.rule_decision, BlockDecision):
            readiness, reason = FinalPromptReadiness.BLOCKED, snapshot.rule_decision.reason
        elif not isinstance(snapshot.rule_decision, ReadyDecision) or compat.remaining_blocker_refs:
            readiness, reason = (
                FinalPromptReadiness.BLOCKED,
                "Current native obligations remain blocking.",
            )
        else:
            readiness = (
                FinalPromptReadiness.READY_WITH_UNRESOLVED
                if unresolved
                else FinalPromptReadiness.READY
            )
            reason = snapshot.rule_decision.reason
        base_description = _description(snapshot, dictionary, facts, constraints, unresolved)
    if len(_pending_descriptions) != len(snapshot.protection_projection.pending_requests):
        raise ValueError("Pending output requires every actual sourced logical request")
    if snapshot.protection_projection.pending_requests:
        readiness, reason = (
            FinalPromptReadiness.BLOCKED,
            "Explicit scoped KEEP confirmation is required.",
        )
    description_payload = dict(
        schema_version="3.0.0",
        locale=snapshot.locale,
        authoritative_revision_id=snapshot.revision.revision_id,
        text=base_description.text
        + (" " + " ".join(_pending_descriptions) if _pending_descriptions else ""),
        unresolved_summary=(*base_description.unresolved_summary, *_pending_descriptions),
        current_frame=snapshot.current_frame,
        protection_projection_hash=snapshot.protection_projection.content_hash,
        compatibility_projection_hash=(
            snapshot.compatibility_projection.content_hash
            if snapshot.compatibility_projection
            else None
        ),
        sealed_frontier_hash=snapshot.native_frontier.content_hash
        if snapshot.native_frontier
        else None,
    )
    # Pending disclosures are part of the description budget too. Reuse the
    # existing typed capacity error before Pydantic's structural validation.
    _check_current_text_capacity(description_payload["text"])
    description = UserReadableJewelryDescriptionV3(
        **description_payload,
        content_hash=contract_hash(
            "jewelai.UserReadableJewelryDescription/3.0.0", description_payload
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
        schema_version="4.0.0",
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
        prompt_text="JEWELAI INTERNAL FINAL PROMPT 4.0.0\n" + text.split("\n", 1)[1],
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
    # The exact renderer check is also run by the source model's inherited validator.
    source = CanonicalInternalFinalPromptV4(
        **payload, content_hash=contract_hash("jewelai.InternalFinalPrompt/4.0.0", payload)
    )
    assert source.prompt_text == render_canonical_source_text(source)
    return CanonicalFinalPromptAssemblyV4(description=description, internal_final_prompt=source)
