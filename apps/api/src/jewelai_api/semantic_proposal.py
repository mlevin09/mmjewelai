"""Internal US-01 LLM proposals and source-backed SO arbitration.

This is not a Parser format or a second Product State. LLM output is untrusted;
the existing Parser independently consumes the original text, and only SO's
evidenced decisions may be passed to the existing Matrix/State machinery.
"""

from typing import Annotated, Literal
from uuid import UUID

from jewelai_domain.clarification_state import StrictEvidenceModel
from jewelai_domain.dictionary import DictionaryCategory
from jewelai_parser.knowledge_matcher import KnowledgeLibraryMatcher
from pydantic import Field, StringConstraints, model_validator

VERSION = "jewelai.us01.semantic-proposal/1.0.0"
Short = Annotated[str, StringConstraints(strict=True, max_length=160)]


class SourceSpan(StrictEvidenceModel):
    start: int = Field(strict=True, ge=0, le=2000)
    end: int = Field(strict=True, gt=0, le=2000)
    text: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("Source span must be nonempty and ordered")
        return self


class SemanticChange(StrictEvidenceModel):
    proposal_id: Short
    target: Short
    value: str | int | float
    operation: Literal["set", "keep", "remove"] = "set"
    component: Literal["product", "product_body", "stone", "center_stone", "side_stones", "unknown"]
    disposition: Literal["selection", "question", "recommendation", "uncertain", "rejected"]
    source: SourceSpan | None = None
    source_phrase: (
        Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2000)] | None
    ) = None
    selection_index: int | None = Field(default=None, strict=True, ge=0, le=0)
    quantity_scope: Literal["EACH", "PAIR", "TOTAL"] | None = None
    unit: Short | None = None

    @model_validator(mode="after")
    def one_source(self):
        if (
            sum(
                value is not None
                for value in (self.source, self.source_phrase, self.selection_index)
            )
            != 1
        ):
            raise ValueError("Exactly one raw span or typed selection source is required")
        return self


class SemanticProposal(StrictEvidenceModel):
    contract_version: Literal["jewelai.us01.semantic-proposal/1.0.0"] = VERSION
    based_on_revision: UUID
    intent: Literal["creation", "information", "greeting", "uncertain"]
    changes: tuple[SemanticChange, ...] = Field(default=(), max_length=24)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({c.proposal_id for c in self.changes}) != len(self.changes):
            raise ValueError("Proposal identities must be unique")
        return self


class ArbitrationDecision(StrictEvidenceModel):
    proposal_id: str
    outcome: Literal["ACCEPT", "CLARIFY", "NO_COMMIT"]
    reason: Literal[
        "source_mismatch",
        "not_a_selection",
        "source_not_selected",
        "scope_unresolved",
        "unsupported_target",
        "unqualified_term",
        "interpreter_disagreement",
        "protected_state",
        "existing_value",
        "explicit_source",
        "competing_values",
        "invalid_revision",
        "matrix_blocked",
    ]
    parser_candidate_ids: tuple[str, ...] = ()
    mapping_ids: tuple[str, ...] = ()
    source_span: SourceSpan | None = None


# These are existing canonical initial-creation bindings, not inferred bindings
# from Policy.effect or from arbitrary concept kinds. Stone groups are not made.
_BINDINGS = {
    "jewelry_type": ("product", DictionaryCategory.JEWELRY_TYPE, "jewelry_type"),
    "metal.material": ("product_body", DictionaryCategory.METAL_MATERIAL, "metal_material"),
    "metal.color": ("product_body", DictionaryCategory.METAL_COLOR, "metal_color"),
}


def _qualified_mapping(change, dictionary, runtime, locale):
    """A DIRECT release mapping or existing Dictionary supplies lexical meaning.

    Core conversation does not require complete professional Knowledge coverage.
    A missing source term remains unresolved; no external/future catalog fallback.
    """
    if runtime is not None:
        match = KnowledgeLibraryMatcher(runtime).match(
            change.source.text, locale=locale, allowed_concept_ids=(str(change.value),)
        )
        concepts = {c.concept_id: c.kind for c in runtime.domain_knowledge}
        if (
            match.outcome == "resolved"
            and match.candidate.mapping_mode == "DIRECT"
            and concepts.get(str(change.value)) == _BINDINGS[change.target][2]
        ):
            return (match.candidate.mapping_id,)
    try:
        entry = dictionary[str(change.value)]
    except KeyError:
        return ()
    if entry.category != _BINDINGS[change.target][1]:
        return ()
    from jewelai_domain.dictionary import DictionaryLocale, normalize_dictionary_text

    requested = DictionaryLocale(locale)
    terms = (entry.canonical_terms.for_locale(requested), *entry.synonyms.for_locale(requested))

    if normalize_dictionary_text(change.source.text) in {
        normalize_dictionary_text(t) for t in terms
    }:
        return (f"dictionary:{entry.domain_id}",)
    return ()


def arbitrate(
    proposal, *, text, parsed, revision, dictionary, runtime=None, locale="en", selections=()
):
    """Compare actual independent evidence; agreement is not consent or authority.

    A missing Parser candidate can be accepted by a direct source/mapping proof.
    A guessed entity, count scope or unsupported target requires clarification.
    Only existing approved first-creation targets can reach the Matrix in US-01.
    """
    from .first_turn import (
        _CREATION,
        CreationFact,
        _direct_creation_subject,
        creation_body_ownership,
    )

    # Offsets are SO evidence, not model arithmetic. A compact model may quote
    # a phrase; only a UNIQUE exact occurrence can establish its source span.
    # Repeated or missing quotes remain unresolved, never an arbitrary first hit.
    anchored = []
    import re

    for change in proposal.changes:
        if change.source_phrase is not None:
            hits = tuple(re.finditer(re.escape(change.source_phrase), text))
            if len(hits) == 1:
                match = hits[0]
                change = change.model_copy(
                    update={
                        "source": SourceSpan(
                            start=match.start(), end=match.end(), text=match.group()
                        ),
                        "source_phrase": None,
                    }
                )
        anchored.append(change)
    proposal = proposal.model_copy(update={"changes": tuple(anchored)})

    results = []
    products = [c for c in proposal.changes if c.target == "jewelry_type"]
    product = products[0] if len(products) == 1 else None
    predicate = _CREATION.match(text)
    source_selected = bool(
        product is not None
        and product.source is not None
        and predicate is not None
        and _direct_creation_subject(
            parsed,
            CreationFact(
                target="jewelry_type",
                value=str(product.value),
                candidate_id=product.proposal_id,
                start=product.source.start,
                end=product.source.end,
                text=product.source.text,
                mapping_ids=(),
            ),
            predicate,
        )
    )
    if product is not None and product.selection_index is not None and selections:
        # A separately retained dropdown can accompany a bare literal metal
        # phrase. Require full raw-span coverage: no hidden question, negation,
        # alternative, information noun or unrelated owner can be skipped.
        remaining = list(text)
        for change in proposal.changes:
            if (
                change.source is not None
                and change.target in {"metal.material", "metal.color"}
                and change.disposition == "selection"
                and change.operation == "set"
                and text[change.source.start : change.source.end] == change.source.text
            ):
                remaining[change.source.start : change.source.end] = " " * (
                    change.source.end - change.source.start
                )
        import re

        source_selected = not re.sub(r"[\s.!]", "", "".join(remaining))

    def verified_sources(target):
        return tuple(
            c.source
            for c in proposal.changes
            if c.target == target
            and c.source is not None
            and text[c.source.start : c.source.end] == c.source.text
            and _qualified_mapping(c, dictionary, runtime, locale)
        )

    materials = verified_sources("metal.material")
    colors = (None, *verified_sources("metal.color"))
    literal_selection = bool(product and product.selection_index is not None and source_selected)
    for c in proposal.changes:
        # Ownership belongs to this exact source occurrence, not the first
        # same-valued material/color proposal elsewhere in the utterance.
        body_owned = literal_selection or any(
            creation_body_ownership(text, product.source if product else None, c.source, color)[0]
            for color in colors
        )
        color_owned = literal_selection or any(
            creation_body_ownership(text, product.source if product else None, material, c.source)[
                1
            ]
            for material in materials
        )
        peers = (
            tuple(
                p
                for p in parsed.candidates
                if c.source is not None
                and p.evidence.start < c.source.end
                and c.source.start < p.evidence.end
                and p.target == c.target
            )
            if parsed
            else ()
        )
        ids = tuple(p.candidate_id for p in peers)
        mappings = ()
        if proposal.based_on_revision != revision.revision_id:
            outcome, reason = "NO_COMMIT", "invalid_revision"
        elif c.source is not None and text[c.source.start : c.source.end] != c.source.text:
            outcome, reason = "NO_COMMIT", "source_mismatch"
        elif c.source is None and c.selection_index is None:
            outcome, reason = "CLARIFY", "source_mismatch"
        elif proposal.intent != "creation" or c.disposition != "selection" or c.operation != "set":
            outcome, reason = "NO_COMMIT", "not_a_selection"
        elif c.selection_index is not None:
            selected = (
                selections[c.selection_index] if len(selections) > c.selection_index else None
            )
            if (
                selected is None
                or c.target != "jewelry_type"
                or selected.value != c.value
                or c.component != "product"
            ):
                outcome, reason = "NO_COMMIT", "source_mismatch"
            else:
                from .natural_turn import product_options

                options = product_options(runtime, locale) if runtime is not None else ()
                mappings = tuple(o["mapping_id"] for o in options if o["value"] == c.value)
                competing = (
                    tuple(
                        p
                        for p in parsed.candidates
                        if p.target == "jewelry_type"
                        and p.normalized_values
                        and p.normalized_values != (c.value,)
                    )
                    if parsed
                    else ()
                )
                outcome, reason = (
                    ("CLARIFY", "competing_values")
                    if competing
                    else ("ACCEPT", "explicit_source")
                    if mappings
                    else ("CLARIFY", "unqualified_term")
                )
        elif any(
            p.classification not in {"requirement", "preference"} or p.certainty != "explicit"
            for p in peers
        ):
            outcome, reason = "CLARIFY", "interpreter_disagreement"
        elif c.target not in _BINDINGS:
            outcome, reason = (
                "CLARIFY",
                "scope_unresolved" if "stone" in c.target else "unsupported_target",
            )
        elif c.component != _BINDINGS[c.target][0] or c.quantity_scope is not None or c.unit:
            outcome, reason = "CLARIFY", "scope_unresolved"
        elif not source_selected:
            outcome, reason = "CLARIFY", "source_not_selected"
        elif (
            c.target == "metal.material"
            and not body_owned
            or c.target == "metal.color"
            and not color_owned
        ):
            outcome, reason = "CLARIFY", "scope_unresolved"
        elif not (mappings := _qualified_mapping(c, dictionary, runtime, locale)):
            outcome, reason = "CLARIFY", "unqualified_term"
        elif any(p.normalized_values and str(c.value) not in p.normalized_values for p in peers):
            outcome, reason = "CLARIFY", "interpreter_disagreement"
        else:
            old = revision.design
            for key in c.target.split("."):
                old = getattr(old, key)
            if old is not None and getattr(old, "value", None) != c.value:
                outcome, reason = (
                    "NO_COMMIT",
                    "protected_state" if old.locked or old.confirmed else "existing_value",
                )
            else:
                outcome, reason = "ACCEPT", "explicit_source"
        if outcome == "ACCEPT":
            old = revision.design
            for key in c.target.split("."):
                old = getattr(old, key)
            if old is not None and getattr(old, "value", None) != c.value:
                outcome, reason = (
                    "NO_COMMIT",
                    "protected_state" if old.locked or old.confirmed else "existing_value",
                )
        results.append(
            ArbitrationDecision(
                proposal_id=c.proposal_id,
                outcome=outcome,
                reason=reason,
                parser_candidate_ids=ids,
                mapping_ids=mappings,
                source_span=c.source
                if c.source is not None and text[c.source.start : c.source.end] == c.source.text
                else None,
            )
        )
    # Both interpreters agreeing does not select one of two incompatible facts.
    conflicting = {
        c.target
        for c in proposal.changes
        if len(
            {
                str(other.value)
                for other in proposal.changes
                if other.target == c.target and other.disposition == "selection"
            }
        )
        > 1
    }
    return tuple(
        d.model_copy(update={"outcome": "CLARIFY", "reason": "competing_values"})
        if c.target in conflicting and d.outcome == "ACCEPT"
        else d
        for c, d in zip(proposal.changes, results, strict=True)
    )
