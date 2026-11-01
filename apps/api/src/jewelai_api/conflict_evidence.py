"""F04 source-backed material conflicts. This boundary never edits canonical state."""

import hashlib
import re
from typing import Literal
from uuid import UUID

from jewelai_domain.clarification_state import (
    F04_PROFILE,
    InputContext,
    Sha256,
    TargetRef,
    evidence_bytes,
    evidence_hash,
)
from jewelai_domain.dictionary import DictionaryCategory, EntryLifecycle
from jewelai_domain.models import DomainId, ImmutableModel
from jewelai_parser import FullMessageParseResult, parse_full_message
from jewelai_parser.full_message import (
    _assertion_breaks,
    _certainty_for,
    _classification_for,
    _sentence_bounds,
    _source_dictionary_material_ids,
)
from pydantic import Field, model_validator


class Occurrence(ImmutableModel):
    message_id: UUID
    message_content_sha256: Sha256
    candidate_id: str
    evidence_start: int = Field(strict=True, ge=0)
    evidence_end: int = Field(strict=True, gt=0)
    evidence_text: str
    normalized_dictionary_id: DomainId
    dictionary_category: Literal["metal_material"]
    classification: Literal["requirement"]
    certainty: Literal["explicit", "ambiguous"]
    normalization_source: Literal["domain_dictionary"]
    authority: Literal["USER_EXPLICIT_REQUIREMENT"]
    source_language: Literal["en", "ru", "mixed", "undetermined"]
    source_revision_id: UUID
    source_cycle_id: UUID


class SpanRef(ImmutableModel):
    message_id: UUID
    start: int = Field(strict=True, ge=0)
    end: int = Field(strict=True, gt=0)
    text: str


def stable_id(prefix, namespace, identity):
    return (
        prefix
        + hashlib.sha256(namespace.encode("ascii") + b"\0" + evidence_bytes(identity)).hexdigest()
    )


class ConflictEvidence(ImmutableModel):
    schema_version: Literal["1.0.0"]
    conflict_id: str = Field(pattern=r"^conflict_[0-9a-f]{64}$")
    context: InputContext
    target: TargetRef
    kind: Literal["alternative", "competing", "equivalent"]
    occurrences: tuple[Occurrence, ...] = Field(min_length=2)
    normalized_values: tuple[DomainId, ...] = Field(min_length=1)
    connective_evidence: tuple[SpanRef, ...]
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_identity(self):
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        if evidence_hash(payload) != self.content_hash:
            raise ValueError("Conflict evidence checksum mismatch")
        identity = {k: v for k, v in payload.items() if k != "conflict_id"}
        if self.conflict_id != stable_id("conflict_", "jewelai.f04.conflict/1.0.0", identity):
            raise ValueError("Conflict evidence identity mismatch")
        values = tuple(sorted({o.normalized_dictionary_id for o in self.occurrences}))
        if values != self.normalized_values or ((len(values) == 1) != (self.kind == "equivalent")):
            raise ValueError("Conflict classification/value mismatch")
        if self.target != TargetRef(
            concrete_target="metal.material",
            owner_kind="product_body",
            owner_id=None,
            group_id=None,
        ):
            raise ValueError("Material conflict requires resolved product-body scope")
        if len({o.candidate_id for o in self.occurrences}) != len(self.occurrences):
            raise ValueError("Conflict cannot duplicate a recognition occurrence")
        keys = tuple(
            (
                str(o.message_id),
                o.evidence_start,
                o.evidence_end,
                o.candidate_id,
                o.normalized_dictionary_id,
            )
            for o in self.occurrences
        )
        if keys != tuple(sorted(keys)):
            raise ValueError("Conflict occurrences must retain deterministic source order")
        if len({o.message_content_sha256 for o in self.occurrences}) != 1:
            raise ValueError("One Message cannot have multiple source-content hashes")
        if any(o.evidence_end - o.evidence_start != len(o.evidence_text) for o in self.occurrences):
            raise ValueError("Conflict source span length mismatch")
        if len({o.message_id for o in self.occurrences}) != 1:
            raise ValueError("Temporal corrections are not simultaneous conflicts")
        if self.kind == "equivalent" and any(o.certainty != "explicit" for o in self.occurrences):
            raise ValueError("Equivalent application requires explicit certainty")
        if (self.kind == "alternative") != bool(self.connective_evidence):
            raise ValueError("Alternative requires actual connective evidence")
        for o in self.occurrences:
            if (o.source_revision_id, o.source_cycle_id) != (
                self.context.source_revision_id,
                self.context.source_enrichment_cycle_id,
            ):
                raise ValueError("Conflict source context mismatch")
        return self


def product_body_material_conflict(parsed, *, message, context, dictionary, knowledge_runtime=None):
    """Consume actual persisted Message plus existing parser authority/scope, not detail prose."""
    parsed = FullMessageParseResult.model_validate(parsed)
    context = InputContext.model_validate(context)
    if message.actor != "user" or message.session_id != context.scope.session_id:
        raise ValueError("Conflict Message actor/session scope mismatch")
    if message.content != parsed.original_text or context.contract_profile != F04_PROFILE:
        raise ValueError("Conflict input must match the persisted Message")
    if dictionary.artifact_version != context.artifact_pins.dictionary_artifact_version:
        raise ValueError("Conflict Dictionary pin mismatch")
    verified_parse = parse_full_message(
        message.content,
        locale=parsed.requested_locale,
        dictionary=dictionary,
        knowledge_runtime=knowledge_runtime,
    )
    if verified_parse != parsed:
        raise ValueError("Conflict evidence does not match deterministic source parsing")
    text = message.content
    source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    eligible = []
    unresolved = False
    for c in parsed.candidates:
        if c.target != "metal.material" or c.subject != "product_body":
            continue
        if c.classification != "requirement":
            continue
        if c.normalization_source != "domain_dictionary":
            # Recognition mirrors and recommendations cannot compete as explicit user facts.
            continue
        if c.certainty not in {"explicit", "ambiguous"}:
            unresolved = True
            continue
        if (
            _classification_for(text, c.evidence.start, c.evidence.end) != "requirement"
            or _certainty_for(text, c.evidence.start, c.evidence.end, "explicit") != "explicit"
        ):
            unresolved = True
            continue
        # Existing deterministic parsing owns inflection/alias normalization. Revalidation above
        # proves these IDs against the actual source without inventing a second normalization path.
        ids = set(_source_dictionary_material_ids(text, c, dictionary))
        if len(ids) != 1 or any(
            value not in dictionary
            or dictionary[value].category != DictionaryCategory.METAL_MATERIAL
            or dictionary[value].lifecycle != EntryLifecycle.ACTIVE
            for value in ids
        ):
            unresolved = True
            continue
        if not ids.issubset(set(c.normalized_values)):
            raise ValueError("Lexical identity differs from parsed choice evidence")
        eligible.append(
            Occurrence(
                message_id=message.message_id,
                message_content_sha256=source_hash,
                candidate_id=c.candidate_id,
                evidence_start=c.evidence.start,
                evidence_end=c.evidence.end,
                evidence_text=c.evidence.text,
                normalized_dictionary_id=ids.pop(),
                dictionary_category="metal_material",
                classification="requirement",
                certainty=c.certainty,
                normalization_source="domain_dictionary",
                authority="USER_EXPLICIT_REQUIREMENT",
                source_language=parsed.detected_language,
                source_revision_id=context.source_revision_id,
                source_cycle_id=context.source_enrichment_cycle_id,
            )
        )
    if len(eligible) < 2 or unresolved:
        return None
    eligible.sort(
        key=lambda o: (
            str(o.message_id),
            o.evidence_start,
            o.evidence_end,
            o.candidate_id,
            o.normalized_dictionary_id,
        )
    )
    values = tuple(sorted({o.normalized_dictionary_id for o in eligible}))
    connectives = []
    for left, right in zip(eligible, eligible[1:], strict=False):
        if left.normalized_dictionary_id == right.normalized_dictionary_id:
            continue
        a, b = left.evidence_end, right.evidence_start
        if b - a > 30 or _sentence_bounds(text, left.evidence_start, left.evidence_end)[1] < b:
            continue
        if any(a <= x and y <= b for x, y in _assertion_breaks(text)):
            continue
        for match in re.finditer(r"\b(?:or|или|либо)\b", text[a:b], re.I):
            connectives.append(
                SpanRef(
                    message_id=message.message_id,
                    start=a + match.start(),
                    end=a + match.end(),
                    text=match.group(),
                )
            )
    kind = "equivalent" if len(values) == 1 else "alternative" if connectives else "competing"
    if kind == "equivalent" and any(o.certainty != "explicit" for o in eligible):
        return None
    payload = dict(
        schema_version="1.0.0",
        context=context.model_dump(mode="json"),
        target=TargetRef(
            concrete_target="metal.material",
            owner_kind="product_body",
            owner_id=None,
            group_id=None,
        ).model_dump(mode="json"),
        kind=kind,
        occurrences=[o.model_dump(mode="json") for o in eligible],
        normalized_values=list(values),
        connective_evidence=[s.model_dump(mode="json") for s in connectives],
    )
    payload["conflict_id"] = stable_id("conflict_", "jewelai.f04.conflict/1.0.0", payload)
    return ConflictEvidence(**payload, content_hash=evidence_hash(payload))
