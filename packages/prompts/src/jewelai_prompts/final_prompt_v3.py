"""F04 final outputs from one exact canonical snapshot and verified current frontier.

Existing fact/constraint/description formatters are reused. Historical answers retain
their original flags/hashes but cannot independently decide current readiness.
"""

from typing import Literal

from jewelai_domain.clarification_state import (
    CanonicalAvailabilityOverlay,
    CauseDefinition,
    EffectiveUnresolvedFrontier,
    OccurrenceRef,
    Sha256,
    StrictEvidenceModel,
    TargetRef,
    evidence_hash,
    validate_availability_overlay,
)
from jewelai_domain.rules_v2 import RuleDecisionV2
from pydantic import model_validator

from .downstream_preparation import (
    CanonicalInternalFinalPromptV2_1,
    check_ifp_v2_1_capacity,
)
from .enrichment import StructuredPromptEnrichmentResultV2, enrichment_projection
from .final_prompt import (
    FinalPromptAssembly,
    FinalPromptReadiness,
    FinalPromptSnapshot,
    FinalPromptUnresolvedDetail,
    UserReadableJewelryDescription,
    _constraints,
    _description,
    _design_facts,
    _enrichment_evidence,
    _render_internal_prompt,
    _target_label,
    _validate_snapshot,
)
from .handoff import InternalFinalPromptHandoff


class FinalPromptSnapshotV2(FinalPromptSnapshot, StrictEvidenceModel):
    schema_version: Literal["2.0.0"]
    contract_profile: Literal["jewelai.prompt-enrichment.f04/2.0.0"]
    enrichment_result: StructuredPromptEnrichmentResultV2
    rule_decision: RuleDecisionV2
    effective_unresolved_frontier: EffectiveUnresolvedFrontier
    cause_definitions: tuple[CauseDefinition, ...]

    @model_validator(mode="after")
    def validate_current_frontier(self):
        core = self.effective_unresolved_frontier.frontier_core
        if (
            core.current_revision_id != self.revision.revision_id
            or core.revision_sha256 != evidence_hash(self.revision)
            or core.scope.session_id != self.session_id
            or core.scope.organization_id != self.organization_id
            or {c.cause_id for c in self.cause_definitions}
            != {c.cause_id for c in core.cause_states}
            or (
                self.artifact_versions.question_artifact_version,
                self.artifact_versions.rules_artifact_version,
                self.artifact_versions.enrichment_version,
            )
            != ("2.0.0", "2.0.0", "2.0.0")
        ):
            raise ValueError("F final snapshot scope/frontier mismatch")
        validate_availability_overlay(
            self.enrichment_result.availability_overlay, self.revision, scope=core.scope
        )
        return self


class UserReadableJewelryDescriptionV2(UserReadableJewelryDescription, StrictEvidenceModel):
    schema_version: Literal["2.0.0"]
    effective_frontier_hash: Sha256


class FinalPromptUnresolvedDetailV3(FinalPromptUnresolvedDetail, StrictEvidenceModel):
    cause_id: str
    kind: Literal[
        "information_gap",
        "material_alternative",
        "material_competing",
        "preference_offer",
        "knowledge_offer",
        "unbound_request",
    ]
    owner: TargetRef
    criticality: Literal["BLOCKING", "NONBLOCKING"]
    source_occurrence_refs: tuple[OccurrenceRef, ...]


def render_ifp_v3_text(prompt):
    text = _render_internal_prompt(
        prompt.description,
        prompt.design_facts,
        prompt.constraints,
        prompt.unresolved_details,
        prompt.readiness,
        prompt.parametric_references,
    )
    text = "JEWELAI INTERNAL FINAL PROMPT 3.0.0\n" + text.split("\n", 1)[1]
    lines = [text, "CANONICAL AVAILABILITY"]
    for entry in prompt.availability_overlay.entries:
        line = f"{entry.target.concrete_target}: {entry.availability}"
        if entry.unknown_requirement is not None:
            line += f"; unknown_requirement={entry.unknown_requirement}"
        if entry.not_applicable is not None:
            line += f"; reason={entry.not_applicable.reason}"
        lines.append(line)
    lines.append("HISTORICAL DECISIONS ARE AUDIT EVIDENCE, NOT CURRENT BLOCKERS")
    return "\n".join(lines)


class CanonicalInternalFinalPromptV3(CanonicalInternalFinalPromptV2_1, StrictEvidenceModel):
    schema_version: Literal["3.0.0"]
    contract_profile: Literal["jewelai.prompt-enrichment.f04/2.0.0"]
    description: UserReadableJewelryDescriptionV2
    unresolved_details: tuple[FinalPromptUnresolvedDetailV3, ...]
    availability_overlay: CanonicalAvailabilityOverlay
    effective_unresolved_frontier: EffectiveUnresolvedFrontier

    @model_validator(mode="after")
    def validate_structured_text(self):
        core = self.effective_unresolved_frontier.frontier_core
        if (
            self.description.content_hash != self.description_content_hash
            or self.description.effective_frontier_hash
            != self.effective_unresolved_frontier.content_hash
            or self.description.authoritative_revision_id != self.product_state_revision_id
            or core.current_revision_id != self.product_state_revision_id
            or self.availability_overlay.canonical_revision_id != self.product_state_revision_id
            or self.availability_overlay.scope != core.scope
            or core.scope.organization_id != self.organization_id
            or core.scope.session_id != self.session_id
            or core.scope.design_id != self.design_id
            or self.artifact_versions.enrichment_version != "2.0.0"
            or (
                self.artifact_versions.question_artifact_version,
                self.artifact_versions.rules_artifact_version,
            )
            != ("2.0.0", "2.0.0")
        ):
            raise ValueError("IFP3 current source binding mismatch")
        current = {c.cause_id: c for c in core.cause_states if c.status == "OPEN"}
        if set(current) != {d.cause_id for d in self.unresolved_details} or len(current) != len(
            self.unresolved_details
        ):
            raise ValueError("IFP3 unresolved details do not match current causes")
        if any(
            d.blocking != current[d.cause_id].blocks_current
            or d.criticality != current[d.cause_id].criticality
            or d.owner != current[d.cause_id].availability_target_ref
            for d in self.unresolved_details
        ):
            raise ValueError("IFP3 unresolved criticality/owner mismatch")
        if (
            any(c.blocks_current for c in current.values())
            and self.readiness != FinalPromptReadiness.BLOCKED
        ):
            raise ValueError("IFP3 readiness bypasses a current blocker")
        if self.prompt_text != render_ifp_v3_text(self):
            raise ValueError("IFP3 structured source text mismatch")
        check_ifp_v2_1_capacity(self.prompt_text)
        return self


class CanonicalFinalPromptAssemblyV3(FinalPromptAssembly, StrictEvidenceModel):
    description: UserReadableJewelryDescriptionV2
    internal_final_prompt: CanonicalInternalFinalPromptV3


class CanonicalInternalFinalPromptHandoffV3(InternalFinalPromptHandoff, StrictEvidenceModel):
    schema_version: Literal["3.0.0"]
    internal_final_prompt_schema_version: Literal["3.0.0"]
    internal_final_prompt: CanonicalInternalFinalPromptV3


def assemble_internal_final_prompt_v3(snapshot, *, dictionary, templates):
    snapshot = FinalPromptSnapshotV2.model_validate(snapshot)
    _validate_snapshot(snapshot, dictionary=dictionary, templates=templates)
    facts = _design_facts(snapshot)
    constraints = _constraints(snapshot, facts)
    evidence = _enrichment_evidence(snapshot, facts)
    frontier = snapshot.effective_unresolved_frontier
    definitions = {c.cause_id: c for c in snapshot.cause_definitions}
    unresolved = []
    summaries = []
    for state in frontier.frontier_core.cause_states:
        if state.status != "OPEN":
            continue
        cause = definitions[state.cause_id]
        classification = (
            "ambiguous"
            if cause.kind.startswith("material_")
            else "unaccepted_recommendation"
            if cause.kind == "knowledge_offer"
            else "deferred"
            if cause.kind in {"preference_offer", "unbound_request"}
            else "missing"
        )
        if state.last_answer_ref is not None and state.last_answer_ref.decision in {
            "SKIP",
            "UNKNOWN",
        }:
            classification = "skipped" if state.last_answer_ref.decision == "SKIP" else "unknown"
        target = cause.target.concrete_target
        unresolved.append(
            FinalPromptUnresolvedDetailV3(
                target=target,
                classification=classification,
                blocking=state.blocks_current,
                source_ids=tuple(
                    str(r.message_id) + ":" + r.candidate_id for r in cause.source_candidate_refs
                ),
                cause_id=cause.cause_id,
                kind=cause.kind,
                owner=cause.target,
                criticality=state.criticality,
                source_occurrence_refs=cause.source_candidate_refs,
            )
        )
        label = _target_label(target, snapshot.locale)
        if cause.kind in {"preference_offer", "knowledge_offer"}:
            summaries.append(
                f"Unanswered optional offer about {label}"
                if snapshot.locale == "en"
                else f"Неотвеченное необязательное предложение о параметре «{label}»"
            )
        elif cause.kind.startswith("material_"):
            known = any(
                e.target == cause.target and e.availability == "VALUE"
                for e in snapshot.enrichment_result.availability_overlay.entries
            )
            summaries.append(
                (
                    "Unaccepted request about product-body metal remains unanswered"
                    if snapshot.locale == "en"
                    else "Непринятый запрос о металле основы изделия остаётся без ответа"
                )
                if known
                else (
                    "Product-body metal choice remains unresolved"
                    if snapshot.locale == "en"
                    else "Выбор металла основы изделия остаётся неуточнённым"
                )
            )
        else:
            summaries.append(
                f"{label}: clarification remains open"
                if snapshot.locale == "en"
                else f"{label}: уточнение остаётся открытым"
            )
    # Unbound source requests cannot be assigned invented canonical owners or
    # causal TargetRefs. Retain their exact wording as noncanonical disclosure.
    # Multiple recognition mirrors may share a phrase; display it once while
    # retaining every immutable source-evidence entry in the IFP audit.
    unbound_wording = tuple(
        dict.fromkeys(
            e.original_wording for e in snapshot.constraint_evidence if e.status == "unresolved"
        )
    )
    summaries.extend(
        (
            "Unaccepted source request: "
            if snapshot.locale == "en"
            else "Непринятый исходный запрос: "
        )
        + "«"
        + wording
        + "»"
        for wording in unbound_wording
    )
    base_description = _description(
        snapshot,
        dictionary,
        facts,
        constraints,
        (),
        _empty_text=(
            "No affirmative design facts have been accepted yet."
            if snapshot.locale == "en"
            else "Утвердительные факты об изделии пока не приняты."
        ),
    )
    text = base_description.text
    # Unknown is a canonical qualifier, not a new professional criticality policy.
    for entry in snapshot.enrichment_result.availability_overlay.entries:
        if entry.availability == "UNKNOWN":
            label = _target_label(entry.target.concrete_target, snapshot.locale)
            qualifier = {
                "required": ("information requested", "сведения запрошены"),
                "optional": ("optional information", "необязательные сведения"),
                "undetermined": (
                    "requirement undetermined",
                    "необходимость сведений не определена",
                ),
            }[entry.unknown_requirement][snapshot.locale == "ru"]
            text += (
                f" {label}: "
                + ("unknown" if snapshot.locale == "en" else "неизвестно")
                + f" ({qualifier})."
            )
        elif entry.availability == "NOT_APPLICABLE":
            label = _target_label(entry.target.concrete_target, snapshot.locale)
            text += (
                f" {label}: "
                + ("not applicable" if snapshot.locale == "en" else "не применимо")
                + f" — {entry.not_applicable.reason}."
            )
    if summaries:
        text += (
            (" Still open: " if snapshot.locale == "en" else " Остаётся уточнить: ")
            + "; ".join(summaries)
            + "."
        )
    desc_payload = dict(
        schema_version="2.0.0",
        locale=snapshot.locale,
        authoritative_revision_id=snapshot.revision.revision_id,
        text=text,
        unresolved_summary=tuple(summaries),
        effective_frontier_hash=frontier.content_hash,
    )
    description = UserReadableJewelryDescriptionV2(
        **desc_payload, content_hash=evidence_hash(desc_payload)
    )
    readiness = (
        FinalPromptReadiness.BLOCKED
        if snapshot.rule_decision.decision != "ready"
        or any(s.blocks_current for s in frontier.frontier_core.cause_states)
        else FinalPromptReadiness.READY_WITH_UNRESOLVED
        if unresolved or unbound_wording
        else FinalPromptReadiness.READY
    )
    payload = dict(
        schema_version="3.0.0",
        contract_profile=snapshot.contract_profile,
        session_id=snapshot.session_id,
        organization_id=snapshot.organization_id,
        design_id=snapshot.revision.design_id,
        product_state_revision_id=snapshot.revision.revision_id,
        enrichment_cycle_id=snapshot.enrichment_cycle_id,
        enrichment_cycle_number=snapshot.enrichment_cycle_number,
        locale=snapshot.locale,
        readiness=readiness,
        readiness_reason=snapshot.rule_decision.reason,
        description_content_hash=description.content_hash,
        description=description,
        parametric_references=snapshot.enrichment_result.parametric_references,
        disclosures=enrichment_projection(snapshot.enrichment_result).disclosures,
        design_facts=facts,
        constraints=constraints,
        unresolved_details=tuple(unresolved),
        enrichment_evidence=evidence,
        decision_lineage=snapshot.decision_lineage,
        constraint_evidence=snapshot.constraint_evidence,
        knowledge_release=snapshot.knowledge_release,
        artifact_versions=snapshot.artifact_versions,
        enrichment_result_content_hash=snapshot.enrichment_result.content_hash,
        availability_overlay=snapshot.enrichment_result.availability_overlay,
        effective_unresolved_frontier=frontier,
    )
    from types import SimpleNamespace

    payload["prompt_text"] = render_ifp_v3_text(SimpleNamespace(**payload))
    check_ifp_v2_1_capacity(payload["prompt_text"])
    prompt = CanonicalInternalFinalPromptV3(**payload, content_hash=evidence_hash(payload))
    return CanonicalFinalPromptAssemblyV3(description=description, internal_final_prompt=prompt)
