"""F05 explicit interpreter, leaving the entire historical 1.1 implementation intact.

The extension only adds sourced preservation grammar. It does not normalize
historical payloads or discard contextual candidates from old parses.
"""

import re
from typing import Literal

from .full_message import (
    _AMBIGUITY,
    CandidateApplication,
    CandidateCertainty,
    CandidateClassification,
    CandidateSubject,
    EvidenceSpan,
    FullMessageParseResult,
    NormalizationSource,
    StructuredCandidate,
    _certainty_for,
    _classification_for,
    _intent_bounds,
)
from .full_message import (
    parse_full_message as parse_legacy,
)


class FullMessageParseResultV1_2(FullMessageParseResult):
    parse_version: Literal["1.2.0"] = "1.2.0"


_CENTER_KEEP = re.compile(
    r"\b(?:сохранить|не\s+менять)\s+(?:существующ\w+\s+)?центральн\w+\s+кам\w*"
    r"(?:\s+без\s+изменений)?\b|"
    r"\b(?:keep|preserve|do\s+not\s+change)\s+(?:the\s+)?center[- ]stone\s+shape"
    r"(?:\s+unchanged)?\b",
    re.I,
)


def _govern_preservation(text, candidate):
    """Preservation words are evidence, not proof of affirmative authority.

    Mask only the preservation predicate itself: 'do not change' and 'без
    изменений' are positive preservation idioms, while an external rejection
    still governs the assertion. Reuse the frozen offset/scope primitives,
    without changing the historical interpreter or inventing cancellation.
    """
    start, end = candidate.evidence.start, candidate.evidence.end
    left, right = _intent_bounds(text, start, end)
    masked = text[:start] + " " * (end - start) + text[end:]
    polarity = _classification_for(masked, start, end)
    certainty = _certainty_for(text, start, end, candidate.certainty)
    if _AMBIGUITY.search(text[left:right]):
        certainty = CandidateCertainty.AMBIGUOUS
    if polarity != CandidateClassification.REQUIREMENT:
        certainty = CandidateCertainty.UNRESOLVED
    if certainty == CandidateCertainty.EXPLICIT:
        return candidate
    # Keep the governing qualifier/rejection in the quoted unresolved evidence.
    while left < right and text[left].isspace():
        left += 1
    while right > left and text[right - 1].isspace():
        right -= 1
    return candidate.model_copy(
        update=dict(
            certainty=certainty,
            evidence=EvidenceSpan(start=left, end=right, text=text[left:right]),
            detail="Uncertain or rejected preservation wording is not KEEP authority.",
        )
    )


def parse_full_message(text, *, locale, dictionary, knowledge_runtime=None):
    """Explicit 1.2 result; candidate offsets and all independent facts are retained."""
    legacy = parse_legacy(
        text, locale=locale, dictionary=dictionary, knowledge_runtime=knowledge_runtime
    )
    additions = []
    for match in _CENTER_KEEP.finditer(text):
        if any(
            candidate.classification == CandidateClassification.PRESERVATION
            and candidate.evidence.start <= match.start()
            and candidate.evidence.end >= match.end()
            for candidate in legacy.candidates
        ):
            continue
        additions.append(
            StructuredCandidate(
                candidate_id=f"f05_preservation_{match.start()}_{match.end()}",
                target=None,
                subject=CandidateSubject.CENTER_STONE,
                classification=CandidateClassification.PRESERVATION,
                certainty=CandidateCertainty.EXPLICIT,
                evidence=EvidenceSpan(start=match.start(), end=match.end(), text=match.group()),
                semantic_subject="component.center_stone",
                normalization_source=NormalizationSource.DETERMINISTIC_PATTERN,
                application=CandidateApplication.STRUCTURED_EVIDENCE_ONLY,
                detail="Explicit sourced preservation, never a canonical value update.",
            )
        )
    protected = tuple((c.evidence.start, c.evidence.end) for c in additions)
    candidates = tuple(
        c
        for c in legacy.candidates
        if not any(start <= c.evidence.start and c.evidence.end <= end for start, end in protected)
    ) + tuple(additions)
    payload = legacy.model_dump(mode="python", exclude={"parse_version", "candidates"})
    candidates = tuple(
        _govern_preservation(text, c)
        if c.classification == CandidateClassification.PRESERVATION
        else c
        for c in candidates
    )
    return FullMessageParseResultV1_2(
        **payload,
        candidates=tuple(
            sorted(candidates, key=lambda c: (c.evidence.start, c.evidence.end, c.candidate_id))
        ),
    )
