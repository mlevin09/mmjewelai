"""Owner-approved T10-10 binding using existing evidence DTOs, not new parser targets.

Knowledge supplies the vocabulary/evidence; only explicit, locally scoped user
language supplies a value. Policy prose never executes. No canonical state writes.
"""

import re

from jewelai_domain.knowledge_runtime import validate_compiled_knowledge

from .knowledge_matcher import KnowledgeLibraryMatcher, ResolvedKnowledgeMatch

TARGET = "composition.symmetry_mode"
VALUE = "asymmetrical"
CONCEPT = "asymmetry"
CONTEXT = "jewelry_composition"
POLICIES = frozenset({"STYLE-10-02", "STYLE-10-06", "STYLE-10-07"})
SOURCE_SHA256 = "43cda0eddf6e33dc15a120ad8c0025ed047824f4a98d377726edee70587b6b64"

_PRODUCT = (
    r"\b(?:ring(?![- ]shaped)|jewel(?:ry|lery)(?:\s+(?:design|composition))?|"
    r"кольц\w*|ювелирн\w*\s+(?:украшени\w*|дизайн\w*|композиц\w*))"
)
_AFTER = re.compile(r"^\s+" + _PRODUCT + r"\b", re.I)
_BEFORE = re.compile(_PRODUCT + r"\s+(?:(?:is|be|should be|must be|будет|должно быть)\s+)?$", re.I)
_POST_PRODUCT = re.compile(
    r"(?:is|be|should|must|does|do|was|are|with|without|in|for|from|of|please|and|but|"
    r"не|без|с|из|будет|должно|нужно|ненужно|нежелательно)\b",
    re.I,
)
_UNCERTAIN = re.compile(
    r"\b(?:maybe|perhaps|possibly|consider|recommend\w*|suggest\w*|reject\w*|avoid|"
    r"if|whether|might|could|example|label|word|term|возможно|может|если|пример|термин|"
    r"рекоменд\w*|предлож\w*|отверг\w*|сомнева\w*|не\s+уверен\w*|нужно\s+ли|"
    r"doubt\w*|unsure|uncertain|not\s+sure)\b",
    re.I,
)
_PRESERVE = re.compile(r"\bне\s+выравнивай\s+его\b|\bdo\s+not\s+make\s+it\s+symmetrical\b", re.I)
_SYMMETRIC = re.compile(r"\b(?:symmetrical|symmetric|симметрич\w*)\b", re.I)
_REJECT = re.compile(
    r"\b(?:not|no|without|never|reject\w*|avoid|unwanted|unnecessary|undesired|"
    r"не|без|ненуж\w*|нежелательн\w*)\b|"
    r"\b(?:don|doesn|isn|wasn|wouldn|shouldn|can)['’]t\b",
    re.I,
)
_NON_JEWELRY_CONTEXT = re.compile(r"\b(?:website|photograph\w*|сайт\w*|фотограф\w*)\b", re.I)
_SENTENCE_BOUNDARIES = ".!?;"
_INSTRUCTION_BOUNDARIES = _SENTENCE_BOUNDARIES + ",—–"
_INDEPENDENT_SEPARATOR = re.compile(r"\s*(?:,\s*(?:(?:and|и)\b\s*)?|[—–]\s*|(?:and|и)\b\s+)", re.I)


def _bounds(text: str, start: int, end: int, separators: str) -> tuple[int, int]:
    edges = [
        i
        for i, mark in enumerate(text)
        if mark in separators
        and not (
            mark == "."
            and 0 < i < len(text) - 1
            and text[i - 1].isdigit()
            and text[i + 1].isdigit()
        )
    ]
    left = max((i for i in edges if i < start), default=-1) + 1
    right = min((i for i in edges if i >= end), default=len(text))
    return left, right


def _mask_spans(text: str, spans) -> str:
    """A same-length analysis view only; original text and offsets are untouched."""
    characters = list(text)
    for start, end in spans:
        characters[start:end] = " " * (end - start)
    return "".join(characters)


def _preservation_clauses(text: str):
    for match in _PRESERVE.finditer(text):
        left, right = _bounds(text, match.start(), match.end(), _INSTRUCTION_BOUNDARIES)
        if not text[left : match.start()].strip() and not text[match.end() : right].strip():
            yield match


def _negative_object_scopes(text: str, constraints: list[dict]):
    """Prove closure of the ENTIRE negative object scope, not its first match.

    A tail can contain only complete existing instructions with their own
    operator, separated as independent clauses. Bare objects (known or unknown),
    alternatives, incomplete lists and arbitrary words cannot prove closure.
    This never invents a prohibition for an unbound list member.
    """
    instructions = [
        (c["evidence"]["start"], c["evidence"]["end"])
        for c in constraints
        if c["certainty"] == "explicit"
        and c["semantic_subject"] is not None
        and c["classification"] in {"prohibition", "preservation"}
    ]
    instructions.extend(m.span() for m in _preservation_clauses(text))
    for candidate in constraints:
        if not (
            candidate["classification"] == "prohibition"
            and candidate["certainty"] == "explicit"
            and candidate["semantic_subject"] is not None
        ):
            continue
        start, end = candidate["evidence"]["start"], candidate["evidence"]["end"]
        _, stop = _bounds(text, start, end, _SENTENCE_BOUNDARIES)
        cursor = end
        closed = True
        while text[cursor:stop].strip():
            separator = _INDEPENDENT_SEPARATOR.match(text, cursor, stop)
            if separator is None:
                closed = False
                break
            cursor = separator.end()
            next_end = max(
                (b for a, b in instructions if a == cursor and b <= stop), default=cursor
            )
            if next_end == cursor:
                closed = False
                break
            cursor = next_end
        yield candidate, stop, closed


def _property_scoped_text(text: str, anchor_end: int, scopes) -> str:
    # A preceding negative may govern the assertion too; do not erase it.
    return _mask_spans(
        text,
        (
            (c["evidence"]["start"], c["evidence"]["end"])
            for c, _, closed in scopes
            if closed and c["semantic_subject"] != TARGET and c["evidence"]["start"] >= anchor_end
        ),
    )


def defer_shared_negative_candidates(text: str, runtime, candidates: list[dict]) -> list[dict]:
    """Retain matched terms in unclosed tails without accepting them as facts."""
    if runtime is None or not has_p010_binding(runtime):
        return candidates
    from .full_message import _special_constraint_candidates

    constraints, _ = _special_constraint_candidates(text)
    ranges = [
        (c["evidence"]["end"], stop)
        for c, stop, closed in _negative_object_scopes(text, constraints)
        if not closed
    ]
    result = []
    for candidate in candidates:
        start, end = candidate["evidence"]["start"], candidate["evidence"]["end"]
        if candidate["classification"] in {"requirement", "preference"} and any(
            a < end and start < b for a, b in ranges
        ):
            candidate = dict(
                candidate,
                certainty="ambiguous",
                parser_update=None,
                application="structured_evidence_only",
                detail=(candidate.get("detail") or "")
                + " Unclosed negative object scope; term retained, not applied.",
            )
        result.append(candidate)
    return result


def _preservation_instructions(text: str, property_view: str):
    """Only complete approved instruction clauses are exempt from rejection.

    Embedded/negated mentions of the same words do not receive the exemption.
    Original offsets remain unchanged for downstream provenance.
    """
    for match in _preservation_clauses(text):
        sentence_left, sentence_right = _bounds(
            text, match.start(), match.end(), _SENTENCE_BOUNDARIES
        )
        surrounding = (
            property_view[sentence_left : match.start()]
            + property_view[match.end() : sentence_right]
        )
        if (
            not _REJECT.search(surrounding)
            and not _UNCERTAIN.search(surrounding)
            and not _NON_JEWELRY_CONTEXT.search(surrounding)
            and text[sentence_right : sentence_right + 1] != "?"
        ):
            yield match


def has_p010_binding(runtime) -> bool:
    runtime = validate_compiled_knowledge(runtime)
    if runtime.contract_version != "1.1.0":
        return False
    sources = {s.source_id: s for s in runtime.sources}
    original = sources.get("SRC-P010-C2-ORIGINAL")
    approval = sources.get("DEC-P010-C2-SYMMETRY")
    if not original or SOURCE_SHA256 not in original.title or not approval:
        return False
    if "6502450359" not in approval.title:
        return False
    claims = {c.claim_id: c for c in runtime.claims}
    required = {"CLM-P010-C2-ASYMMETRY", "CLM-P010-C2-T10-10"}
    if not required.issubset(claims):
        return False
    if any(
        claims[c].source_id != original.source_id
        or approval.source_id not in claims[c].supporting_source_ids
        for c in required
    ):
        return False
    concept = next((c for c in runtime.domain_knowledge if c.concept_id == CONCEPT), None)
    if not concept or concept.kind != "composition_symmetry" or set(concept.claim_ids) != required:
        return False
    policies = {p.policy_id: p for p in runtime.policies}
    return all(
        p in policies
        and policies[p].target == TARGET
        and policies[p].source_kind == "INTERNAL_PRODUCT_DECISION"
        and policies[p].source_refs == (approval.source_id,)
        for p in POLICIES
    )


def symmetry_evidence(text: str, runtime) -> list[dict]:
    """Return ordinary StructuredCandidate payloads; caller assigns stable IDs."""
    from .full_message import (
        CandidateCertainty,
        CandidateClassification,
        CandidateSubject,
        NormalizationSource,
        _classification_for,
        _special_constraint_candidates,
        _structured_candidate,
        _tokens,
    )

    if runtime is None or not has_p010_binding(runtime):
        return []
    matcher = KnowledgeLibraryMatcher(runtime)
    evidence = []
    # Re-derive from raw text, never trust caller-supplied spans to hide negation.
    constraints, _ = _special_constraint_candidates(text)
    scopes = tuple(_negative_object_scopes(text, constraints))
    unresolved_scope = any(not closed for _, _, closed in scopes)
    preservation_by_anchor = {}
    for token in _tokens(text):
        following_product = _AFTER.search(text[token.end :])
        if not (following_product or _BEFORE.search(text[: token.start])):
            continue
        # A product word used as a noun modifier does not establish a jewelry
        # referent (e.g. an unknown compound). Defer; do not grow a noun blacklist.
        compound = False
        if following_product:
            tail = text[token.end + following_product.end() :].lstrip()
            compound = bool(tail and tail[0].isalpha() and not _POST_PRODUCT.match(tail))
        locale = "ru" if any("а" <= c.casefold() <= "я" for c in token.text) else "en"
        # The approved binding is deliberately narrower than future vocabulary
        # additions to the same concept/mapping. No implicit synonym expansion.
        surfaces = {"ru": {"асимметричное"}, "en": {"asymmetric", "asymmetrical"}}
        if token.text.casefold() not in surfaces[locale]:
            continue
        match = matcher.match(
            token.text, locale=locale, context=CONTEXT, allowed_concept_ids={CONCEPT}
        )
        if not isinstance(match, ResolvedKnowledgeMatch):
            continue
        if match.candidate.mapping_id != f"LANG-P010-C2-{locale.upper()}-ASYMMETRY":
            continue
        property_view = _property_scoped_text(text, token.end, scopes)
        preservation = tuple(_preservation_instructions(text, property_view))
        preservation_by_anchor[token.start] = preservation
        scoped_text = _mask_spans(property_view, (item.span() for item in preservation))
        competing = any(
            _classification_for(scoped_text, m.start(), m.end())
            == CandidateClassification.REQUIREMENT
            for m in _SYMMETRIC.finditer(scoped_text)
        )
        # Commas do not terminate a governing rejection/doubt ("Не хочу, чтобы...").
        # Inspect both sides within this sentence, rather than a token prefix or
        # the entire message. Independent sentences keep their own scope.
        left, right = _bounds(scoped_text, token.start, token.end, _SENTENCE_BOUNDARIES)
        scope = scoped_text[left:right]
        classification = _classification_for(scope, token.start - left, token.end - left)
        if _REJECT.search(scope):
            classification = CandidateClassification.PROHIBITION
        uncertain = (
            competing
            or compound
            or unresolved_scope
            or _UNCERTAIN.search(scope)
            or _NON_JEWELRY_CONTEXT.search(scope)
            or scoped_text[right : right + 1] == "?"
        )
        evidence.append(
            _structured_candidate(
                text,
                token.start,
                token.end,
                target=None,
                subject=CandidateSubject.OVERALL_DESIGN,
                classification=classification,
                certainty=CandidateCertainty.AMBIGUOUS
                if uncertain
                else CandidateCertainty.EXPLICIT,
                raw_value=token.text,
                normalized_values=(CONCEPT,),
                semantic_subject=TARGET,
                normalization_source=NormalizationSource.KNOWLEDGE_LIBRARY,
                detail=(
                    f"Approved P0-10 T10-10 binding; {match.candidate.mapping_id}; "
                    "CLM-P010-C2-T10-10; /mini_tests/9"
                ),
            )
        )
    if any(e["classification"] == CandidateClassification.PROHIBITION for e in evidence):
        # Contradictory same-message evidence has no invented winner.
        for item in evidence:
            if item["classification"] == CandidateClassification.REQUIREMENT:
                item["certainty"] = CandidateCertainty.AMBIGUOUS
    positive = [
        e
        for e in evidence
        if e["classification"] == CandidateClassification.REQUIREMENT
        and e["certainty"] == CandidateCertainty.EXPLICIT
    ]
    # A preservation phrase alone has no invented referent. It never creates LOCK.
    if len(positive) == 1:
        for match in preservation_by_anchor[positive[0]["evidence"]["start"]]:
            evidence.append(
                _structured_candidate(
                    text,
                    match.start(),
                    match.end(),
                    target=None,
                    subject=CandidateSubject.OVERALL_DESIGN,
                    classification=CandidateClassification.PRESERVATION,
                    certainty=CandidateCertainty.EXPLICIT,
                    raw_value=match.group(0),
                    normalized_values=(),
                    semantic_subject=TARGET,
                    normalization_source=NormalizationSource.DETERMINISTIC_PATTERN,
                    detail="Preserve explicit asymmetry; no confirmation or intrinsic LOCK.",
                )
            )
    return evidence


def verified_symmetry_candidate(candidate, parsed, runtime) -> bool:
    """Re-derive scoped evidence from exact text and the verified pinned runtime."""
    from .full_message import StructuredCandidate

    actual = candidate.model_dump(mode="json", exclude={"candidate_id"})
    return any(
        actual
        == StructuredCandidate(candidate_id=candidate.candidate_id, **payload).model_dump(
            mode="json", exclude={"candidate_id"}
        )
        for payload in symmetry_evidence(parsed.original_text, runtime)
    )
