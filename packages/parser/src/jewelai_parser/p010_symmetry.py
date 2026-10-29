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
_UNCERTAIN = re.compile(
    r"\b(?:maybe|perhaps|possibly|consider|recommend\w*|suggest\w*|reject\w*|avoid|"
    r"if|whether|might|could|example|label|word|term|возможно|может|если|пример|термин|"
    r"рекоменд\w*|предлож\w*|отверг\w*|сомнева\w*|не\s+уверен\w*|нужно\s+ли|"
    r"doubt\w*|unsure|uncertain|not\s+sure)\b",
    re.I,
)
_PRESERVE = re.compile(r"\bне\s+выравнивай\s+его\b|\bdo not make it symmetrical\b", re.I)
_SYMMETRIC = re.compile(r"\b(?:symmetrical|symmetric|симметрич\w*)\b", re.I)
_REJECT = re.compile(
    r"\b(?:not|no|without|never|reject\w*|avoid|unwanted|unnecessary|undesired|"
    r"не|без|ненуж\w*|нежелательн\w*)\b|"
    r"\b(?:don|doesn|isn|wasn|wouldn|shouldn|can)['’]t\b",
    re.I,
)
_NON_JEWELRY_CONTEXT = re.compile(r"\b(?:website|photograph\w*|сайт\w*|фотограф\w*)\b", re.I)
_SENTENCE_BOUNDARIES = ".!?;\n"
_INSTRUCTION_BOUNDARIES = _SENTENCE_BOUNDARIES + ",—–"


def _bounds(text: str, start: int, end: int, separators: str) -> tuple[int, int]:
    left = max(text.rfind(mark, 0, start) for mark in separators) + 1
    right = min((i for mark in separators if (i := text.find(mark, end)) >= 0), default=len(text))
    return left, right


def _preservation_instructions(text: str):
    """Only complete approved instruction clauses are exempt from rejection.

    Embedded/negated mentions of the same words do not receive the exemption.
    Original offsets remain unchanged for downstream provenance.
    """
    for match in _PRESERVE.finditer(text):
        left, right = _bounds(text, match.start(), match.end(), _INSTRUCTION_BOUNDARIES)
        if not text[left : match.start()].strip() and not text[match.end() : right].strip():
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
        _structured_candidate,
        _tokens,
    )

    if runtime is None or not has_p010_binding(runtime):
        return []
    matcher = KnowledgeLibraryMatcher(runtime)
    evidence = []
    preservation = tuple(_preservation_instructions(text))
    scoped_text = text
    for instruction in preservation:
        scoped_text = (
            scoped_text[: instruction.start()]
            + " " * (instruction.end() - instruction.start())
            + scoped_text[instruction.end() :]
        )
    competing = any(
        _classification_for(scoped_text, m.start(), m.end()) == CandidateClassification.REQUIREMENT
        for m in _SYMMETRIC.finditer(scoped_text)
    )
    for token in _tokens(text):
        if not (_AFTER.search(text[token.end :]) or _BEFORE.search(text[: token.start])):
            continue
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
        classification = _classification_for(scoped_text, token.start, token.end)
        # Commas do not terminate a governing rejection/doubt ("Не хочу, чтобы...").
        # Inspect both sides within this sentence, rather than a token prefix or
        # the entire message. Independent sentences keep their own scope.
        left, right = _bounds(scoped_text, token.start, token.end, _SENTENCE_BOUNDARIES)
        scope = scoped_text[left:right]
        if _REJECT.search(scope):
            classification = CandidateClassification.PROHIBITION
        uncertain = (
            competing
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
        for match in preservation:
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
