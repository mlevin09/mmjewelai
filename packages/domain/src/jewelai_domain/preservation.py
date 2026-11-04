"""F05 source-anchored preservation evidence, never independent mutation authority.

Whole-component scope comes from the retained canonical schema, not the much
smaller parser write allowlist. Storage must separately verify source, scope,
typed consent, actual revision ancestry and current transaction frame.
"""

import hashlib
import json
from functools import lru_cache
from typing import Literal
from uuid import UUID

from pydantic import model_validator
from pydantic_core import to_jsonable_python

from .clarification_state import EvidenceScope, Sha256, StrictEvidenceModel, TargetRef
from .clarification_state import evidence_hash as canonical_hash
from .continuation import ContinuationObjectReference, ContinuationRecordReference
from .lock_protection import first_locked_change, state_fields
from .models import Stone
from .models_v1_1 import StoneV1_1, validate_design_revision

PROFILE = "jewelai.prompt-enrichment.f05/1.0.0"
RELEASE_TARGETS = frozenset(
    f"center_stone.{field}"
    for field in ("material", "shape", "cut", "weight", "dimensions", "setting")
)
_STONE_MODELS = {"1.0.0": Stone, "1.1.0": StoneV1_1}


class PreservationConflict(ValueError):
    """A transition requires distinct explicit consent or violates canonical LOCK."""

    def __init__(self, targets):
        self.targets = tuple(sorted(set(targets)))
        super().__init__("Canonical change overlaps active preservation")


def contract_hash(domain, value):
    value = to_jsonable_python(value)
    raw = json.dumps(
        {"domain": domain, "value": value},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def anchor_hash(value):
    return contract_hash("jewelai.KeepState/1.0.0", value)


@lru_cache
def protected_targets(schema_version):
    try:
        model = _STONE_MODELS[schema_version]
    except KeyError:
        raise ValueError("Unsupported retained preservation schema") from None
    return tuple(sorted(f"center_stone.{field}" for field in model.model_fields))


@lru_cache
def stone_schema_sha256(schema_version):
    protected_targets(schema_version)
    return canonical_hash(_STONE_MODELS[schema_version].model_json_schema())


def target_state(design, target):
    owner, field = target.split(".")
    if owner != "center_stone" or field not in type(design.center_stone).model_fields:
        raise ValueError("Target is outside the retained center-stone schema")
    return getattr(design.center_stone, field)


class PreservationAnchor(StrictEvidenceModel):
    target: str
    baseline_state_sha256: Sha256


class PreservationRoot(StrictEvidenceModel):
    schema_version: Literal["1.0.0"]
    evidence_id: str
    evidence_hash: Sha256
    source_revision_id: UUID
    source_revision_sha256: Sha256
    source_cycle_id: UUID
    design_id: UUID
    design_schema_version: Literal["1.0.0", "1.1.0"]
    schema_model_sha256: Sha256
    scope_targets: tuple[str, ...]
    original_anchors: tuple[PreservationAnchor, ...]
    content_hash: Sha256

    @model_validator(mode="after")
    def verify(self):
        allowed = protected_targets(self.design_schema_version)
        if (
            not self.scope_targets
            or self.scope_targets != tuple(sorted(set(self.scope_targets)))
            or not set(self.scope_targets).issubset(allowed)
            or (self.scope_targets != allowed and len(self.scope_targets) != 1)
            or tuple(a.target for a in self.original_anchors) != self.scope_targets
            or self.schema_model_sha256 != stone_schema_sha256(self.design_schema_version)
        ):
            raise ValueError("Preservation scope does not match the retained schema")
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        if self.content_hash != contract_hash("jewelai.PreservationRoot/1.0.0", payload):
            raise ValueError("Preservation source integrity mismatch")
        return self


class PreservationRootReference(StrictEvidenceModel):
    evidence_id: str
    content_hash: Sha256
    source_revision_id: UUID
    source_cycle_id: UUID


class ProjectionRoot(StrictEvidenceModel):
    root_ref: PreservationRootReference
    source_revision_id: UUID
    scope_targets: tuple[TargetRef, ...]


class ActivePreservationAnchor(StrictEvidenceModel):
    root_evidence_id: str
    target: TargetRef
    baseline_state_sha256: Sha256
    anchor_revision_id: UUID
    last_accepted_release_ref: ContinuationRecordReference | None


class PendingPreservationRequest(StrictEvidenceModel):
    intent_id: Sha256
    current_offer_ref: ContinuationObjectReference | None
    status: Literal["PENDING", "RECONFIRMATION_REQUIRED"]


class ProtectionProjection(StrictEvidenceModel):
    schema_version: Literal["1.0.0"]
    scope: EvidenceScope
    design_schema_version: Literal["1.0.0", "1.1.0"]
    current_revision_id: UUID
    current_revision_sha256: Sha256
    schema_model_sha256: Sha256
    roots: tuple[ProjectionRoot, ...]
    anchors: tuple[ActivePreservationAnchor, ...]
    pending_requests: tuple[PendingPreservationRequest, ...]
    applied_decision_refs: tuple[ContinuationRecordReference, ...]
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_projection(self):
        if len({p.intent_id for p in self.pending_requests}) != len(self.pending_requests):
            raise ValueError("Pending preservation request IDs must be unique")
        if len({r.id for r in self.applied_decision_refs}) != len(self.applied_decision_refs):
            raise ValueError("Applied release decision references must be unique")
        allowed = protected_targets(self.design_schema_version)
        for root in self.roots:
            targets = tuple(t.concrete_target for t in root.scope_targets)
            if (
                not targets
                or targets != tuple(sorted(set(targets)))
                or not set(targets).issubset(allowed)
                or (targets != allowed and len(targets) != 1)
                or root.source_revision_id != root.root_ref.source_revision_id
                or any(
                    t.owner_kind != "center_stone"
                    or t.owner_id is not None
                    or t.group_id is not None
                    for t in root.scope_targets
                )
            ):
                raise ValueError("Current preservation root has an invalid schema scope")
        expected = {
            (root.root_ref.evidence_id, target.concrete_target)
            for root in self.roots
            for target in root.scope_targets
        }
        actual = tuple((a.root_evidence_id, a.target.concrete_target) for a in self.anchors)
        if (
            len(expected) != len(actual)
            or set(actual) != expected
            or actual != tuple(sorted(actual))
            or len({r.root_ref.evidence_id for r in self.roots}) != len(self.roots)
            or self.schema_model_sha256 != stone_schema_sha256(self.design_schema_version)
        ):
            raise ValueError("Current preservation projection is incomplete")
        if self.content_hash != contract_hash(
            "jewelai.ProtectionProjection/1.0.0",
            self.model_dump(mode="json", exclude={"content_hash"}),
        ):
            raise ValueError("Current preservation projection integrity mismatch")
        return self


def center_target_ref(target):
    if target not in set(protected_targets("1.0.0")) | set(protected_targets("1.1.0")):
        raise ValueError("Target is outside the versioned center-stone schema")
    return TargetRef(
        concrete_target=target, owner_kind="center_stone", owner_id=None, group_id=None
    )


def initial_protection_projection(revision, scope, roots):
    """Restore roots without retroactive consent; reject a contradictory old history."""
    revision = validate_design_revision(revision)
    if scope.design_id != revision.design_id:
        raise ValueError("Preservation projection has a different design scope")
    active = []
    anchors = []
    for root in sorted(roots, key=lambda r: r.evidence_id):
        root = PreservationRoot.model_validate(root)
        if (
            root.design_id != revision.design_id
            or root.design_schema_version != revision.schema_version
        ):
            raise ValueError("Preservation source belongs to another design/schema")
        targets = tuple(center_target_ref(t) for t in root.scope_targets)
        active.append(
            ProjectionRoot(
                root_ref=PreservationRootReference(
                    evidence_id=root.evidence_id,
                    content_hash=root.evidence_hash,
                    source_revision_id=root.source_revision_id,
                    source_cycle_id=root.source_cycle_id,
                ),
                source_revision_id=root.source_revision_id,
                scope_targets=targets,
            )
        )
        for original in root.original_anchors:
            if (
                anchor_hash(target_state(revision.design, original.target))
                != original.baseline_state_sha256
            ):
                raise PreservationConflict((original.target,))
            anchors.append(
                ActivePreservationAnchor(
                    root_evidence_id=root.evidence_id,
                    target=center_target_ref(original.target),
                    baseline_state_sha256=original.baseline_state_sha256,
                    anchor_revision_id=root.source_revision_id,
                    last_accepted_release_ref=None,
                )
            )
    payload = dict(
        schema_version="1.0.0",
        scope=scope,
        design_schema_version=revision.schema_version,
        current_revision_id=revision.revision_id,
        current_revision_sha256=canonical_hash(revision),
        schema_model_sha256=stone_schema_sha256(revision.schema_version),
        roots=tuple(active),
        anchors=tuple(
            sorted(anchors, key=lambda a: (a.root_evidence_id, a.target.concrete_target))
        ),
        pending_requests=(),
        applied_decision_refs=(),
    )
    return ProtectionProjection(
        **payload, content_hash=contract_hash("jewelai.ProtectionProjection/1.0.0", payload)
    )


def build_preservation_root(
    *, evidence_id, evidence_hash, source_revision, source_cycle_id, field=None
):
    revision = validate_design_revision(source_revision)
    targets = protected_targets(revision.schema_version)
    if field is not None:
        target = f"center_stone.{field}"
        if target not in targets:
            raise ValueError("Preservation field is not present in the retained schema")
        targets = (target,)
    payload = dict(
        schema_version="1.0.0",
        evidence_id=evidence_id,
        evidence_hash=evidence_hash,
        source_revision_id=revision.revision_id,
        source_revision_sha256=canonical_hash(revision),
        source_cycle_id=source_cycle_id,
        design_id=revision.design_id,
        design_schema_version=revision.schema_version,
        schema_model_sha256=stone_schema_sha256(revision.schema_version),
        scope_targets=targets,
        original_anchors=tuple(
            PreservationAnchor(
                target=t, baseline_state_sha256=anchor_hash(target_state(revision.design, t))
            )
            for t in targets
        ),
    )
    canonical = to_jsonable_python(payload)
    return PreservationRoot(
        **payload,
        content_hash=contract_hash("jewelai.PreservationRoot/1.0.0", canonical),
    )


def overlapping_preservation_targets(current, proposed_design, roots):
    revision = validate_design_revision(current)
    targets = set()
    for root in roots:
        root = PreservationRoot.model_validate(root)
        if (
            root.design_id != revision.design_id
            or root.design_schema_version != revision.schema_version
        ):
            raise ValueError("Preservation root belongs to a different design or schema")
        targets.update(root.scope_targets)
    return tuple(
        target
        for target in sorted(targets)
        if anchor_hash(target_state(revision.design, target))
        != anchor_hash(target_state(proposed_design, target))
    )


def check_preservation_transition(current, proposed_design, roots):
    """Deny every protected delta; explicit release is a separate verified operation."""
    revision = validate_design_revision(current)
    locked = first_locked_change(state_fields(revision.design), state_fields(proposed_design))
    if locked is not None:
        raise PreservationConflict((".".join(locked),))
    overlaps = overlapping_preservation_targets(revision, proposed_design, roots)
    if overlaps:
        raise PreservationConflict(overlaps)


def validate_scoped_release(before, after, roots, *, target, root_refs, authorization_source):
    """Verify a one-field committed transition after separately verified typed consent.

    This is not an acceptance endpoint: the runtime must prove the exact pending
    request, offer, source Message and live frame. All roots remain immutable;
    their effective anchors can then be derived from this actual child revision.
    """
    before = validate_design_revision(before)
    after = validate_design_revision(after)
    roots = tuple(PreservationRoot.model_validate(root) for root in roots)
    applicable = tuple(
        sorted(
            (root.evidence_id, root.evidence_hash) for root in roots if target in root.scope_targets
        )
    )
    if (
        target not in RELEASE_TARGETS
        or not applicable
        or tuple(sorted(root_refs)) != applicable
        or after.parent_revision_id != before.revision_id
        or after.design_id != before.design_id
        or after.schema_version != before.schema_version
        or after.event.action != "edit"
        or after.event.source != authorization_source
    ):
        raise PreservationConflict((target,))
    locked = first_locked_change(state_fields(before.design), state_fields(after.design))
    if locked is not None:
        raise PreservationConflict((".".join(locked),))
    owner, field = target.split(".")
    original = before.design.model_dump(mode="json")
    changed = after.design.model_dump(mode="json")
    if original[owner][field] == changed[owner][field]:
        raise PreservationConflict((target,))
    # Compare the entire canonical design, not only the protection/write subset.
    changed[owner][field] = original[owner][field]
    if changed != original:
        raise PreservationConflict((target,))
    return anchor_hash(target_state(after.design, target))
