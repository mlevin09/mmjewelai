"""F04 immutable evidence, not an alternative canonical Product State or mutation engine.

The overlay is recomputed from a complete revision. Authority, database currency and
causal acceptance must still be proved by the existing runtime/repository boundary.
"""

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictBool, model_validator
from pydantic_core import to_jsonable_python

from .lock_protection import state_fields
from .models import DomainId, ImmutableModel, KnownValue, MessageSource, NotApplicable, Unknown
from .models_v1_1 import validate_design_revision

F04_PROFILE = "jewelai.prompt-enrichment.f04/2.0.0"
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def evidence_bytes(value):
    """Same pinned compact JSON spelling as the existing canonical preparation boundary."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    else:
        value = to_jsonable_python(value)
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def evidence_hash(value):
    return hashlib.sha256(evidence_bytes(value)).hexdigest()


class StrictEvidenceModel(ImmutableModel):
    """New F evidence rejects silent wire normalization; legacy models are untouched."""

    @classmethod
    def model_validate_json(cls, json_data, **kwargs):
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("Duplicate F04 JSON evidence key")
                result[key] = value
            return result

        def nonfinite(_):
            raise ValueError("F04 JSON evidence requires finite numbers")

        try:
            value = json.loads(json_data, object_pairs_hook=pairs, parse_constant=nonfinite)
        except (ValueError, UnicodeError):
            raise ValueError("Invalid F04 JSON evidence") from None
        checked = cls.model_validate(value, **kwargs)
        if evidence_bytes(value) != evidence_bytes(checked):
            raise ValueError("F04 JSON evidence requires complete explicit fields")
        return checked

    @model_validator(mode="wrap")
    @classmethod
    def preserve_wire_values(cls, value, handler):
        checked = handler(value)
        if isinstance(value, dict):
            supplied = to_jsonable_python(value)
            rendered = checked.model_dump(mode="json")

            def unchanged(raw, canonical):
                if isinstance(raw, dict):
                    return isinstance(canonical, dict) and all(
                        key in canonical and unchanged(item, canonical[key])
                        for key, item in raw.items()
                    )
                if isinstance(raw, list):
                    return (
                        isinstance(canonical, list)
                        and len(raw) == len(canonical)
                        and all(unchanged(a, b) for a, b in zip(raw, canonical, strict=True))
                    )
                return type(raw) is type(canonical) and raw == canonical

            if not unchanged(supplied, rendered):
                raise ValueError("F04 evidence must retain exact typed wire values")
        return checked


class EvidenceScope(StrictEvidenceModel):
    organization_id: UUID
    session_id: UUID
    design_id: UUID


class ReleasePin(StrictEvidenceModel):
    package_id: str
    artifact_version: str
    runtime_sha256: Sha256
    validation_report_sha256: Sha256


class ArtifactPins(StrictEvidenceModel):
    design_schema_version: Literal["1.0.0", "1.1.0"]
    role_artifact_version: str
    dictionary_artifact_version: str
    question_schema_version: Literal["2.0.0"]
    question_artifact_version: Literal["2.0.0"]
    rules_schema_version: Literal["2.0.0"]
    rules_artifact_version: Literal["2.0.0"]
    prompt_template_artifact_version: str
    dictionary_sha256: Sha256
    question_sha256: Sha256
    rules_sha256: Sha256


class InputContext(StrictEvidenceModel):
    scope: EvidenceScope
    contract_profile: Literal["jewelai.prompt-enrichment.f04/2.0.0"]
    source_revision_id: UUID
    source_revision_sha256: Sha256
    source_enrichment_cycle_id: UUID
    source_enrichment_cycle_number: int = Field(strict=True, ge=1)
    release_pin: ReleasePin
    artifact_pins: ArtifactPins


class TargetRef(StrictEvidenceModel):
    concrete_target: str
    owner_kind: Literal[
        "product",
        "product_body",
        "band",
        "prongs",
        "center_stone",
        "side_stones",
        "setting",
        "overall_design",
    ]
    owner_id: DomainId | None
    group_id: DomainId | None


class NotApplicableEvidence(StrictEvidenceModel):
    reason: str
    source: MessageSource


class AvailabilityEntry(StrictEvidenceModel):
    target: TargetRef
    canonical_pointer: str
    availability: Literal["ABSENT", "UNKNOWN", "NOT_APPLICABLE", "VALUE"]
    unknown_requirement: Literal["required", "optional", "undetermined"] | None
    origin: Literal["explicit", "derived", "assumed", "unknown"] | None
    confirmed: StrictBool
    locked: StrictBool
    canonical_state_sha256: Sha256
    revision_event_sha256: Sha256
    not_applicable: NotApplicableEvidence | None


class CanonicalAvailabilityOverlay(StrictEvidenceModel):
    schema_version: Literal["1.0.0"]
    scope: EvidenceScope
    design_schema_version: Literal["1.0.0", "1.1.0"]
    canonical_revision_id: UUID
    canonical_revision_sha256: Sha256
    entries: tuple[AvailabilityEntry, ...]
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_hash(self):
        if self.content_hash != evidence_hash(
            self.model_dump(mode="json", exclude={"content_hash"})
        ):
            raise ValueError("Availability overlay integrity mismatch")
        return self


def _pointer(revision, segments):
    """Resolve real snapshot structure, retaining array indexes only in the JSON pointer."""
    current = revision.design
    result = ["design"]
    for segment in segments:
        while isinstance(current, KnownValue):
            current = current.value
            result.append("value")
        if isinstance(current, tuple):
            from .lock_protection import stable_item_id

            index = next(i for i, item in enumerate(current) if stable_item_id(item) == segment)
            result.append(str(index))
            current = current[index]
        else:
            result.append(segment)
            current = getattr(current, segment)
    return "/" + "/".join(s.replace("~", "~0").replace("/", "~1") for s in result)


def _target(revision, path):
    group_id = None
    owner_id = None
    owner = "product"
    if path[0] == "metal":
        owner = "product_body"
        if len(path) > 2 and path[1] == "components":
            owner_id = path[2]
    elif path[0] == "center_stone":
        owner = "center_stone"
    elif path[0] == "side_stones" and len(path) > 1:
        owner = "side_stones"
        group_id = path[1]
    elif path[0] == "decorative_elements" and len(path) > 1:
        owner_id = path[1]
    return TargetRef(
        concrete_target=".".join(path), owner_kind=owner, owner_id=owner_id, group_id=group_id
    )


def build_availability_overlay(revision, *, scope):
    revision = validate_design_revision(revision)
    scope = EvidenceScope.model_validate(scope)
    if scope.design_id != revision.design_id:
        raise ValueError("Availability overlay design scope mismatch")
    event_hash = evidence_hash(revision.event)
    entries = []
    for path, state in sorted(state_fields(revision.design).items()):
        availability = (
            "ABSENT"
            if state is None
            else "UNKNOWN"
            if isinstance(state, Unknown)
            else "NOT_APPLICABLE"
            if isinstance(state, NotApplicable)
            else "VALUE"
        )
        entries.append(
            AvailabilityEntry(
                target=_target(revision, path),
                canonical_pointer=_pointer(revision, path),
                availability=availability,
                unknown_requirement=state.requirement if isinstance(state, Unknown) else None,
                origin=getattr(state, "origin", None),
                confirmed=getattr(state, "confirmed", False),
                locked=getattr(state, "locked", False),
                canonical_state_sha256=evidence_hash(state),
                revision_event_sha256=event_hash,
                not_applicable=NotApplicableEvidence(reason=state.reason, source=state.source)
                if isinstance(state, NotApplicable)
                else None,
            )
        )
    payload = dict(
        schema_version="1.0.0",
        scope=scope.model_dump(mode="json"),
        design_schema_version=revision.schema_version,
        canonical_revision_id=str(revision.revision_id),
        canonical_revision_sha256=evidence_hash(revision),
        entries=[e.model_dump(mode="json") for e in entries],
    )
    return CanonicalAvailabilityOverlay(**payload, content_hash=evidence_hash(payload))


def validate_availability_overlay(overlay, revision, *, scope):
    """A valid checksum alone is not proof of canonical content, scope or freshness."""
    actual = CanonicalAvailabilityOverlay.model_validate(overlay)
    if actual != build_availability_overlay(revision, scope=scope):
        raise ValueError("Availability overlay does not match the canonical revision")
    return actual


class RuleRef(StrictEvidenceModel):
    artifact_version: str
    artifact_sha256: Sha256
    rule_id: str
    rule_version: str


class OccurrenceRef(StrictEvidenceModel):
    message_id: UUID
    candidate_id: str
    message_content_sha256: Sha256


class GapSatisfiedPredicate(StrictEvidenceModel):
    kind: Literal["gap_satisfied"]
    concrete_target: str
    original_gap_state: Literal["absent", "unknown", "unsatisfied"]


class MaterialChoicePredicate(StrictEvidenceModel):
    kind: Literal["material_choice"]
    target: Literal["metal.material"]
    offered_values: tuple[DomainId, ...] = Field(min_length=2)
    conflict_id: str


class OfferDecidedPredicate(StrictEvidenceModel):
    kind: Literal["offer_decided"]
    semantic_question_id: str
    offered_values: tuple[DomainId, ...]
    source_occurrence_refs: tuple[OccurrenceRef, ...]


Predicate = Annotated[
    GapSatisfiedPredicate | MaterialChoicePredicate | OfferDecidedPredicate,
    Field(discriminator="kind"),
]


class CauseDefinition(StrictEvidenceModel):
    schema_version: Literal["1.0.0"]
    cause_id: str = Field(pattern=r"^cause_[0-9a-f]{64}$")
    scope: EvidenceScope
    target: TargetRef
    kind: Literal[
        "information_gap",
        "material_alternative",
        "material_competing",
        "preference_offer",
        "knowledge_offer",
        "unbound_request",
    ]
    origin_cycle_id: UUID
    origin_revision_id: UUID
    origin_plan_id: UUID
    source_candidate_refs: tuple[OccurrenceRef, ...]
    source_conflict_id: str | None
    rule_ref: RuleRef | None
    release_pin: ReleasePin
    artifact_pins: ArtifactPins
    resolution_predicate: Predicate
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_hash(self):
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        if evidence_hash(payload) != self.content_hash:
            raise ValueError("Cause definition checksum mismatch")
        identity = {k: v for k, v in payload.items() if k != "cause_id"}
        expected = (
            "cause_"
            + hashlib.sha256(b"jewelai.f04.cause/1.0.0\0" + evidence_bytes(identity)).hexdigest()
        )
        if expected != self.cause_id:
            raise ValueError("Cause definition identity mismatch")
        if self.kind.startswith("material_") and (
            not isinstance(self.resolution_predicate, MaterialChoicePredicate)
            or self.target.concrete_target != "metal.material"
            or self.target.owner_kind != "product_body"
            or self.target.owner_id is not None
            or self.target.group_id is not None
            or self.source_conflict_id != self.resolution_predicate.conflict_id
        ):
            raise ValueError("Material cause scope/predicate mismatch")
        return self


class AnswerReference(StrictEvidenceModel):
    record_id: UUID
    content_hash: Sha256
    decision: Literal["SELECT_OPTION", "ACCEPT", "REJECT", "SKIP", "UNKNOWN"]
    outcome: str


class ResolutionReference(StrictEvidenceModel):
    result_kind: Literal["clarification", "correction"]
    record_id: UUID
    content_hash: Sha256
    assertion_index: int = Field(strict=True, ge=0)


class CauseState(StrictEvidenceModel):
    cause_id: str = Field(pattern=r"^cause_[0-9a-f]{64}$")
    status: Literal["OPEN", "RESOLVED", "SUPERSEDED", "REJECTED"]
    criticality: Literal["BLOCKING", "NONBLOCKING"]
    offer_state: Literal["AVAILABLE", "DORMANT", "UNREPRESENTABLE", "PROTECTED", "NONE"]
    last_answer_ref: AnswerReference | None
    resolution_ref: ResolutionReference | None
    superseded_by_cause_id: str | None
    rule_ref: RuleRef | None
    availability_target_ref: TargetRef

    @property
    def blocks_current(self):
        return self.status == "OPEN" and self.criticality == "BLOCKING"

    @model_validator(mode="after")
    def validate_resolution(self):
        if self.status == "OPEN" and (
            self.resolution_ref is not None or self.superseded_by_cause_id is not None
        ):
            raise ValueError("Open cause cannot claim a resolving result")
        if self.status != "OPEN" and self.resolution_ref is None:
            raise ValueError("Closed cause requires exact resolving evidence")
        if self.status != "SUPERSEDED" and self.superseded_by_cause_id is not None:
            raise ValueError("Only superseded cause may link a replacement")
        return self


class FrontierCore(StrictEvidenceModel):
    schema_version: Literal["1.0.0"]
    scope: EvidenceScope
    current_revision_id: UUID
    revision_sha256: Sha256
    profile: Literal["jewelai.prompt-enrichment.f04/2.0.0"]
    cause_states: tuple[CauseState, ...]
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_hash_and_order(self):
        ids = tuple(c.cause_id for c in self.cause_states)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("Current causes require unique stable order")
        if (
            evidence_hash(self.model_dump(mode="json", exclude={"content_hash"}))
            != self.content_hash
        ):
            raise ValueError("Frontier core checksum mismatch")
        return self


class PlanReference(StrictEvidenceModel):
    plan_id: UUID
    content_hash: Sha256


class OriginalQuestionReference(StrictEvidenceModel):
    cause_id: str
    plan_id: UUID
    question_id: str


class EffectiveUnresolvedFrontier(StrictEvidenceModel):
    schema_version: Literal["1.0.0"]
    frontier_core: FrontierCore
    current_plan_ref: PlanReference
    origin_plan_refs: tuple[PlanReference, ...]
    origin_question_refs: tuple[OriginalQuestionReference, ...]
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_hash(self):
        if (
            evidence_hash(self.model_dump(mode="json", exclude={"content_hash"}))
            != self.content_hash
        ):
            raise ValueError("Effective frontier checksum mismatch")
        return self
