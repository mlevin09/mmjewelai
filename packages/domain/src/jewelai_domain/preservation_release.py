"""F05 scoped release evidence and pure current-anchor projection.

These types are not authorization. The runtime must verify the original positive
ParserProposal, actual Messages, exact current offer/command and scoped DB frame
before using a release. No consent is inferred from free text or a hash alone.
"""

from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, TypeAdapter, model_validator

from .clarification_state import Sha256, StrictEvidenceModel, TargetRef, evidence_hash
from .compatibility import CompatibilitySourceSpan
from .continuation import (
    ContinuationContext,
    ContinuationFrame,
    ContinuationObjectReference,
    ContinuationRecordReference,
)
from .lock_protection import first_locked_change, state_fields
from .models import Explicit, KnownValue, MessageSource, State, Text
from .models_v1_1 import validate_design_revision
from .preservation import (
    _STONE_MODELS,
    RELEASE_TARGETS,
    PreservationConflict,
    PreservationRoot,
    PreservationRootReference,
    ProtectionProjection,
    anchor_hash,
    contract_hash,
    target_state,
    validate_scoped_release,
)

type ReleaseActions = tuple[Literal["ACCEPT"], Literal["REJECT"]] | tuple[Literal["REJECT"]]


def requested_value_hash(value):
    return contract_hash("jewelai.KeepRequestedValue/1.0.0", value)


def _verify_content(value, name):
    if value.content_hash != contract_hash(
        f"jewelai.{name}/1.0.0", value.model_dump(mode="json", exclude={"content_hash"})
    ):
        raise ValueError("Scoped release evidence integrity mismatch")


def _verify_identity(value, name, field):
    if getattr(value, field) != contract_hash(
        f"jewelai.{name}/1.0.0", value.model_dump(mode="json", exclude={field, "content_hash"})
    ):
        raise ValueError("Scoped release identity mismatch")


def _ordered_roots(roots):
    keys = tuple(r.evidence_id for r in roots)
    return bool(keys) and keys == tuple(sorted(set(keys)))


class KeepReleaseIntent(StrictEvidenceModel):
    schema_version: Literal["1.0.0"]
    intent_id: Sha256
    context: ContinuationContext
    origin_head: ContinuationFrame
    correction_record_id: UUID
    source: MessageSource
    message_sha256: Sha256
    parse_version: Literal["1.2.0"]
    parse_hash: Sha256
    proposal_hash: Sha256
    source_candidate_ids: tuple[Text, ...] = Field(min_length=1)
    source_spans: tuple[CompatibilitySourceSpan, ...] = Field(min_length=1)
    target: TargetRef
    original_before_state: State[JsonValue] | None
    requested_state: State[JsonValue]
    requested_value_sha256: Sha256
    keep_roots: tuple[PreservationRootReference, ...] = Field(min_length=1)
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_intent(self):
        target, requested = self.target, self.requested_state
        if (
            target.concrete_target not in RELEASE_TARGETS
            or target.owner_kind != "center_stone"
            or target.owner_id is not None
            or target.group_id is not None
            or not isinstance(requested, Explicit)
            or requested.source != self.source
            or requested.confirmed
            or requested.locked
            or self.context.parser_interpreter_id != "f05-1.2"
            or self.requested_value_sha256 != requested_value_hash(requested.value)
            or self.source_candidate_ids != tuple(sorted(set(self.source_candidate_ids)))
            or not _ordered_roots(self.keep_roots)
        ):
            raise ValueError("Release intent lacks an exact supported sourced positive delta")
        # Reuse the actual retained field type, including units and finite bounds.
        schema = self.context.artifact_pins.design_schema_version
        model = _STONE_MODELS.get(schema)
        if model is None:
            raise ValueError("Release intent has an unsupported retained schema")
        annotation = model.model_fields[target.concrete_target.split(".")[1]].annotation
        canonical = TypeAdapter(annotation).validate_python(requested.model_dump(mode="json"))
        if evidence_hash(canonical) != evidence_hash(requested):
            raise ValueError("Release request must already contain an exact canonical wrapper")
        _verify_identity(self, "KeepReleaseIntent", "intent_id")
        _verify_content(self, "KeepReleaseIntent")
        return self


class KeepReofferBinding(StrictEvidenceModel):
    schema_version: Literal["1.0.0"]
    binding_id: Sha256
    intent_id: Sha256
    previous_offer_ref: ContinuationObjectReference | None
    previous_binding_ref: ContinuationObjectReference | None
    owning_plan_id: UUID
    source_head: ContinuationFrame
    current_before_state_sha256: Sha256
    anchor_set_sha256: Sha256
    applicable_keep_roots: tuple[PreservationRootReference, ...] = Field(min_length=1)
    allowed_decisions: ReleaseActions
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_binding(self):
        if not _ordered_roots(self.applicable_keep_roots):
            raise ValueError("Release binding needs the exact ordered applicable root union")
        if (self.previous_offer_ref is None) != (self.previous_binding_ref is None):
            raise ValueError("Re-offer requires both previous offer and binding references")
        _verify_identity(self, "ReofferBinding", "binding_id")
        _verify_content(self, "ReofferBinding")
        return self


class KeepReleaseOffer(StrictEvidenceModel):
    schema_version: Literal["1.0.0"]
    offer_id: Sha256
    intent_id: Sha256
    binding: KeepReofferBinding
    target: TargetRef
    requested_value_sha256: Sha256
    locale: Literal["en", "ru"]
    rendered_question: Text
    allowed_decisions: ReleaseActions
    owning_plan_id: UUID
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_offer(self):
        if (
            self.binding.intent_id != self.intent_id
            or self.binding.owning_plan_id != self.owning_plan_id
            or self.binding.allowed_decisions != self.allowed_decisions
            or self.target.concrete_target not in RELEASE_TARGETS
        ):
            raise ValueError("Release offer does not match its exact binding")
        _verify_identity(self, "Offer", "offer_id")
        _verify_content(self, "Offer")
        return self


class ReleasedTarget(StrictEvidenceModel):
    target: TargetRef
    before_state_sha256: Sha256
    after_state_sha256: Sha256


class KeepReleaseDecision(StrictEvidenceModel):
    schema_version: Literal["1.0.0"]
    decision_id: UUID
    request_hash: Sha256
    context: ContinuationContext
    intent_id: Sha256
    offer_id: Sha256
    binding_hash: Sha256
    previous_head: ContinuationFrame
    decision: Literal["ACCEPT", "REJECT"]
    source: MessageSource
    message_sha256: Sha256
    outcome: Literal["APPLIED", "REJECTED"]
    resulting_revision_id: UUID | None
    accepted_target: ReleasedTarget | None
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_decision(self):
        accepted = self.decision == "ACCEPT"
        if (
            accepted != (self.outcome == "APPLIED")
            or accepted != (self.resulting_revision_id is not None)
            or accepted != (self.accepted_target is not None)
        ):
            raise ValueError("Release decision outcome/revision/evidence mismatch")
        _verify_content(self, "KeepReleaseDecision")
        return self


def anchor_set_hash(protection):
    """Exclude pending/offer refs to avoid projection→offer→projection cycles."""
    return contract_hash(
        "jewelai.KeepAnchorSet/1.0.0",
        protection.model_dump(
            mode="json",
            include={
                "scope",
                "design_schema_version",
                "schema_model_sha256",
                "current_revision_id",
                "current_revision_sha256",
                "roots",
                "anchors",
            },
        ),
    )


def _current_projection(protection, before):
    before = validate_design_revision(before)
    protection = ProtectionProjection.model_validate(protection)
    if (
        protection.scope.design_id != before.design_id
        or protection.current_revision_id != before.revision_id
        or protection.current_revision_sha256 != evidence_hash(before)
        or protection.design_schema_version != before.schema_version
        or any(
            a.baseline_state_sha256
            != anchor_hash(target_state(before.design, a.target.concrete_target))
            for a in protection.anchors
        )
    ):
        raise PreservationConflict(("component.center_stone",))
    return before, protection


def project_unprotected_transition(*, before, after, protection):
    """Carry exact anchors across a verified compatible/unrelated command.

    The caller must independently prove the EDIT/source or NO_CHANGE transition
    and append its new plan. Pending logical requests survive but old offers do
    not acquire authority for the new head.
    """
    before, protection = _current_projection(protection, before)
    after = validate_design_revision(after)
    if (
        after.design_id != before.design_id
        or after.schema_version != before.schema_version
        or (
            after != before
            and (after.parent_revision_id != before.revision_id or after.event.action != "edit")
        )
    ):
        raise PreservationConflict(("component.center_stone",))
    locked = first_locked_change(state_fields(before.design), state_fields(after.design))
    changed = tuple(
        a.target.concrete_target
        for a in protection.anchors
        if anchor_hash(target_state(after.design, a.target.concrete_target))
        != a.baseline_state_sha256
    )
    if locked is not None or changed:
        raise PreservationConflict(changed if locked is None else (".".join(locked),))
    payload = protection.model_dump(mode="json", exclude={"content_hash"})
    payload.update(
        current_revision_id=after.revision_id,
        current_revision_sha256=evidence_hash(after),
        pending_requests=tuple(
            p.model_copy(update={"current_offer_ref": None, "status": "RECONFIRMATION_REQUIRED"})
            for p in protection.pending_requests
        ),
    )
    return ProtectionProjection(
        **payload, content_hash=contract_hash("jewelai.ProtectionProjection/1.0.0", payload)
    )


def project_verified_release(
    *, before, after, protection, roots, intent, offer, decision, current_head
):
    """Derive effective anchors after separately validated typed consent/DB CAS.

    No revision or event is created here. A caller must verify the exact immutable
    command against persisted sources/offer/history BEFORE staging its transaction.
    """
    before, protection = _current_projection(protection, before)
    after = validate_design_revision(after)
    intent = KeepReleaseIntent.model_validate(intent)
    offer = KeepReleaseOffer.model_validate(offer)
    decision = KeepReleaseDecision.model_validate(decision)
    current_head = ContinuationFrame.model_validate(current_head)
    roots = tuple(PreservationRoot.model_validate(root) for root in roots)
    target = intent.target.concrete_target
    applicable = tuple(
        sorted(
            (r.evidence_id, r.evidence_hash, r.source_revision_id, r.source_cycle_id)
            for r in roots
            if target in r.scope_targets
        )
    )
    bound = tuple(
        (r.evidence_id, r.content_hash, r.source_revision_id, r.source_cycle_id)
        for r in offer.binding.applicable_keep_roots
    )
    pending = next(
        (p for p in protection.pending_requests if p.intent_id == intent.intent_id), None
    )
    if tuple(sorted((r.evidence_id, r.evidence_hash) for r in roots)) != tuple(
        sorted((r.root_ref.evidence_id, r.root_ref.content_hash) for r in protection.roots)
    ):
        raise PreservationConflict((target,))
    projected_roots = {r.root_ref.evidence_id: r for r in protection.roots}
    if any(
        root.design_id != before.design_id
        or root.design_schema_version != before.schema_version
        or root.source_revision_id != projected_roots[root.evidence_id].root_ref.source_revision_id
        or root.source_cycle_id != projected_roots[root.evidence_id].root_ref.source_cycle_id
        or root.scope_targets
        != tuple(t.concrete_target for t in projected_roots[root.evidence_id].scope_targets)
        for root in roots
    ):
        raise PreservationConflict((target,))
    if (
        decision.context != intent.context
        or decision.context.scope != protection.scope
        or decision.previous_head != current_head
        or current_head.revision_id != before.revision_id
        or current_head.revision_sha256 != evidence_hash(before)
        or decision.intent_id != intent.intent_id
        or offer.intent_id != intent.intent_id
        or offer.target != intent.target
        or offer.requested_value_sha256 != intent.requested_value_sha256
        or decision.offer_id != offer.offer_id
        or decision.binding_hash != offer.binding.content_hash
        or offer.owning_plan_id != current_head.plan_id
        or offer.binding.current_before_state_sha256
        != anchor_hash(target_state(before.design, target))
        or offer.binding.anchor_set_sha256 != anchor_set_hash(protection)
        or applicable != bound
        or not applicable
        or decision.decision not in offer.allowed_decisions
        or pending is None
        or pending.status != "PENDING"
        or pending.current_offer_ref
        != ContinuationObjectReference(id=offer.offer_id, hash=offer.content_hash)
    ):
        raise PreservationConflict((target,))
    anchors = protection.anchors
    applied = protection.applied_decision_refs
    if decision.decision == "ACCEPT":
        accepted = decision.accepted_target
        before_state = target_state(before.design, target)
        after_state = target_state(after.design, target)
        if (
            after_state is None
            or (
                isinstance(before_state, KnownValue)
                and requested_value_hash(before_state.value) == intent.requested_value_sha256
            )
            or decision.resulting_revision_id != after.revision_id
            or accepted.target != intent.target
            or accepted.before_state_sha256 != anchor_hash(target_state(before.design, target))
            or accepted.after_state_sha256 != anchor_hash(target_state(after.design, target))
            or target_state(after.design, target).model_dump(mode="json")
            != intent.requested_state.model_dump(mode="json")
        ):
            raise PreservationConflict((target,))
        value_hash = validate_scoped_release(
            before,
            after,
            roots,
            target=target,
            root_refs=[(r[0], r[1]) for r in applicable],
            authorization_source=decision.source,
        )
        ref = ContinuationRecordReference(id=decision.decision_id, hash=decision.content_hash)
        if any(r.id == ref.id for r in applied):
            raise PreservationConflict((target,))
        anchors = tuple(
            a.model_copy(
                update=dict(
                    baseline_state_sha256=value_hash,
                    anchor_revision_id=after.revision_id,
                    last_accepted_release_ref=ref,
                )
            )
            if a.target.concrete_target == target
            else a
            for a in anchors
        )
        applied = (*applied, ref)
    elif after != before:
        raise PreservationConflict((target,))
    payload = protection.model_dump(mode="json", exclude={"content_hash"})
    payload.update(
        current_revision_id=after.revision_id,
        current_revision_sha256=evidence_hash(after),
        anchors=anchors,
        applied_decision_refs=applied,
        pending_requests=tuple(
            p.model_copy(update={"current_offer_ref": None, "status": "RECONFIRMATION_REQUIRED"})
            for p in protection.pending_requests
            if p.intent_id != intent.intent_id
        ),
    )
    return ProtectionProjection(
        **payload, content_hash=contract_hash("jewelai.ProtectionProjection/1.0.0", payload)
    )
