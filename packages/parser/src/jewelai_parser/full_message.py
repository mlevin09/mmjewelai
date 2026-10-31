"""Deterministic, relationship-aware extraction from complete RU/EN user messages."""

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Literal

from jewelai_domain.dictionary import (
    AmbiguousMatch,
    DictionaryCategory,
    DictionaryLocale,
    DictionaryRegistry,
    ResolvedMatch,
)
from jewelai_domain.knowledge_library import MappingMode
from jewelai_domain.knowledge_runtime import AnyCompiledKnowledge, validate_compiled_knowledge
from jewelai_domain.models import ImmutableModel, Text
from pydantic import Field, JsonValue, model_validator

from .knowledge_matcher import (
    AmbiguousKnowledgeMatch,
    KnowledgeLibraryMatcher,
    ResolvedKnowledgeMatch,
    normalize_knowledge_text,
    ru_morphology_key,
)
from .models import (
    CandidateUpdate,
    DimensionsCandidate,
    ParserTarget,
    StyleTermsCandidate,
    TermCandidate,
    WeightCandidate,
)

FULL_MESSAGE_PARSE_VERSION = "1.1.0"


class MessageLanguage(StrEnum):
    EN = "en"
    RU = "ru"
    MIXED = "mixed"
    UNDETERMINED = "undetermined"


class CandidateClassification(StrEnum):
    REQUIREMENT = "requirement"
    PREFERENCE = "preference"
    PROHIBITION = "prohibition"
    PRESERVATION = "preservation"


class CandidateCertainty(StrEnum):
    EXPLICIT = "explicit"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class CandidateSubject(StrEnum):
    PRODUCT = "product"
    PRODUCT_BODY = "product_body"
    BAND = "band"
    PRONGS = "prongs"
    CENTER_STONE = "center_stone"
    SIDE_STONES = "side_stones"
    SETTING = "setting"
    OVERALL_DESIGN = "overall_design"
    UNKNOWN = "unknown"


class CandidateApplication(StrEnum):
    PARSER_CANDIDATE_READY = "parser_candidate_ready"
    STRUCTURED_EVIDENCE_ONLY = "structured_evidence_only"


class NormalizationSource(StrEnum):
    DOMAIN_DICTIONARY = "domain_dictionary"
    KNOWLEDGE_LIBRARY = "knowledge_library"
    DETERMINISTIC_PATTERN = "deterministic_pattern"
    NONE = "none"


class StructuredTarget(StrEnum):
    JEWELRY_TYPE = "jewelry_type"
    METAL_MATERIAL = "metal.material"
    METAL_COLOR = "metal.color"
    CENTER_STONE_MATERIAL = "center_stone.material"
    CENTER_STONE_SHAPE = "center_stone.shape"
    CENTER_STONE_CUT = "center_stone.cut"
    CENTER_STONE_WEIGHT = "center_stone.weight"
    CENTER_STONE_DIMENSIONS = "center_stone.dimensions"
    CENTER_STONE_SETTING = "center_stone.setting"
    STYLE = "style"
    SIDE_STONE_MATERIAL = "side_stones.{group_id}.stones.material"
    SIDE_STONE_SHAPE = "side_stones.{group_id}.stones.shape"
    SIDE_STONE_CUT = "side_stones.{group_id}.stones.cut"
    SIDE_STONE_WEIGHT = "side_stones.{group_id}.stones.weight"
    SIDE_STONE_DIMENSIONS = "side_stones.{group_id}.stones.dimensions"
    SIDE_STONE_SETTING = "side_stones.{group_id}.stones.setting"
    SIDE_STONE_QUANTITY = "side_stones.{group_id}.quantity"


class EvidenceSpan(ImmutableModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: Text

    @model_validator(mode="after")
    def validate_offsets(self):
        if self.end <= self.start:
            raise ValueError("evidence end must be greater than start")
        return self


class StructuredCandidate(ImmutableModel):
    candidate_id: str
    target: StructuredTarget | None
    subject: CandidateSubject
    classification: CandidateClassification
    certainty: CandidateCertainty
    evidence: EvidenceSpan
    raw_value: JsonValue = None
    normalized_values: tuple[str, ...] = ()
    semantic_subject: str | None = None
    normalization_source: NormalizationSource = NormalizationSource.NONE
    application: CandidateApplication
    parser_update: CandidateUpdate | None = None
    detail: str | None = None

    @model_validator(mode="after")
    def validate_application(self):
        if self.application == CandidateApplication.PARSER_CANDIDATE_READY:
            if self.parser_update is None:
                raise ValueError("parser-ready extraction requires a CandidateUpdate")
            if self.classification in {
                CandidateClassification.PROHIBITION,
                CandidateClassification.PRESERVATION,
            }:
                raise ValueError("constraints cannot be emitted as positive parser updates")
        elif self.parser_update is not None:
            raise ValueError("structured-only extraction cannot contain a CandidateUpdate")
        return self


class FullMessageParseResult(ImmutableModel):
    parse_version: Literal["1.1.0"] = FULL_MESSAGE_PARSE_VERSION
    original_text: Text
    requested_locale: Literal["en", "ru"]
    detected_language: MessageLanguage
    dictionary_artifact_version: str
    knowledge_package_id: str | None = None
    knowledge_artifact_version: str | None = None
    knowledge_runtime_sha256: str | None = None
    candidates: tuple[StructuredCandidate, ...] = ()

    @model_validator(mode="after")
    def validate_evidence_and_runtime_identity(self):
        for candidate in self.candidates:
            span = candidate.evidence
            if span.end > len(self.original_text):
                raise ValueError("evidence span exceeds original input")
            if self.original_text[span.start : span.end] != span.text:
                raise ValueError("evidence span does not match original input")
        runtime_values = (
            self.knowledge_package_id,
            self.knowledge_artifact_version,
            self.knowledge_runtime_sha256,
        )
        if any(value is not None for value in runtime_values) and not all(
            value is not None for value in runtime_values
        ):
            raise ValueError("knowledge runtime identity must be complete or absent")
        return self


@dataclass(frozen=True)
class _Surface:
    text: str
    locale: Literal["en", "ru"]
    category: DictionaryCategory | None
    normalized_id: str
    source: NormalizationSource
    kind: str | None = None


@dataclass(frozen=True)
class _Token:
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class _Found:
    start: int
    end: int
    surface: _Surface
    certainty: CandidateCertainty = CandidateCertainty.EXPLICIT
    normalized_values: tuple[str, ...] = ()


_KIND_TO_CATEGORY = {
    "jewelry_type": DictionaryCategory.JEWELRY_TYPE,
    "gemstone_material": DictionaryCategory.GEMSTONE_MATERIAL,
    "stone_material": DictionaryCategory.GEMSTONE_MATERIAL,
    "stone_shape": DictionaryCategory.STONE_SHAPE,
    "stone_cut": DictionaryCategory.STONE_CUT,
    "stone_setting": DictionaryCategory.STONE_SETTING,
    "metal_material": DictionaryCategory.METAL_MATERIAL,
    "metal_color": DictionaryCategory.METAL_COLOR,
    "style": DictionaryCategory.STYLE,
}

_SUBJECT_PATTERNS = {
    CandidateSubject.CENTER_STONE: re.compile(
        r"\b(?:center|central|centre)[\s-]*(?:stone|gem|diamond|sapphire)?\b|"
        r"(?:в\s+центре|централь\w*\s+(?:кам\w*|сапфир\w*|бриллиант\w*))",
        re.IGNORECASE,
    ),
    CandidateSubject.SIDE_STONES: re.compile(
        r"\b(?:side[\s-]*stones?|stones?\s+on\s+the\s+sides?|diamonds?\s+on\s+the\s+sides?|on\s+(?:each|both)\s+sides?)\b|"
        r"(?:боков\w*\s+кам\w*|кам\w*\s+по\s+бокам|бриллиант\w*\s+по\s+бокам|по\s+бокам|сбоку)",
        re.IGNORECASE,
    ),
    CandidateSubject.PRONGS: re.compile(r"\bprongs?\b|крапан\w*", re.IGNORECASE),
    CandidateSubject.SETTING: re.compile(
        r"\b(?:setting|mount|mounting)\b|закрепк\w*|оправ\w*", re.I
    ),
    CandidateSubject.BAND: re.compile(r"\b(?:band|shank)\b|шинк\w*", re.IGNORECASE),
}

_PREFERENCE = re.compile(
    r"\b(?:prefer|preference|would\s+like|ideally|хочу|предпочита\w*)\b",
    re.IGNORECASE,
)
_AMBIGUITY = re.compile(r"\b(?:maybe|perhaps|possibly|either|or|возможно|может|либо|или)\b", re.I)
_NEGATED_AUXILIARY = (
    r"(?:(?:is|are|was|were|do|does|did|would|will|can|should)\s+not|cannot|"
    r"(?:isn|aren|wasn|weren|don|doesn|didn|wouldn|won|shouldn|can)['’]t)"
)
_NEGATION = re.compile(
    r"\b(?:" + _NEGATED_AUXILIARY + r"|not|no|without|never|reject\w*|avoid|"
    r"unwanted|unnecessary|undesired|ненуж\w*|нежелательн\w*|без|не|никак\w*)\b",
    re.I,
)
# Predicate rejection governs the preceding assertion, unlike a following
# negative object ("gold ring without side stones"). No canonical value is inferred.
_REJECTED_ASSERTION = re.compile(
    r"\b(?:(?:is|are|was|were)\s+(?:not\s+|never\s+)?"
    r"(?:unwanted|unnecessary|undesired)|" + _NEGATED_AUXILIARY + r"\s+(?:be\s+)?"
    r"(?:what|want\w*|need\w*|desir\w*|suit\w*|accept\w*|appeal\w*|interest\w*|choos\w*)|"
    r"не\s+(?:нуж\w*|подход\w*|устраива\w*|интересу\w*|хочу|то\b))\b",
    re.I,
)
_TENTATIVE = re.compile(
    r"\b(?:maybe|perhaps|possibly|might|could|not\s+sure|unsure|uncertain|"
    r"возможно|может(?:\s+быть)?|сомнева\w*|не\s+уверен\w*)\b",
    re.I,
)
_CONTRAST = re.compile(r"\b(?:but|however|но|однако)\b", re.I)
_COORDINATION = re.compile(r",\s*(?:(?:and|и)\b\s*)?|\b(?:and|и)\b|\r?\n", re.I)
_REQUEST_START = re.compile(
    r"\b(?:(?:I|we|я|мы|мне|нам)\s+)?(?:(?:" + _NEGATED_AUXILIARY + r"|не)\s+)?"
    r"(?:want|need|choose|reject|avoid|хотим|нуж(?:ен|на|но|ны)|" + _PREFERENCE.pattern + r")\b",
    re.I,
)
_TOKEN = re.compile(r"[^\W_]+|\d+(?:[.,]\d+)?", re.UNICODE)

_SPECIAL_CONSTRAINTS = (
    (
        re.compile(
            r"\b(?:(?:no|without)\s+(?:a\s+)?|"
            r"(?:please\s+)?(?:do\s+not|don['’]t|never)\s+(?:add|include|use)\s+(?:a\s+)?|"
            r"(?:I\s+)?(?:do\s+not|don['’]t)\s+want\s+(?:a\s+)?|"
            r"без\s+|не\s+(?:добавляй(?:те)?|добавлять|используй(?:те)?|использовать|хочу)\s+)"
            r"(?:halo|гало)\b",
            re.I,
        ),
        CandidateClassification.PROHIBITION,
        CandidateSubject.SETTING,
        ("halo_setting", "halo_style"),
        "feature.halo",
        CandidateCertainty.EXPLICIT,
        "A negative halo constraint has no positive ParserCandidate representation.",
    ),
    (
        re.compile(r"\b(?:add|include|use|with)\s+(?:a\s+)?halo\b", re.I),
        CandidateClassification.REQUIREMENT,
        CandidateSubject.SETTING,
        ("halo_setting", "halo_style"),
        "feature.halo",
        CandidateCertainty.EXPLICIT,
        "A halo requirement is retained as constraint evidence without guessing a schema field.",
    ),
    (
        re.compile(r"\b(?:no|without)\s+(?:an?\s+)?engrav(?:ing|ed)\b", re.I),
        CandidateClassification.PROHIBITION,
        CandidateSubject.OVERALL_DESIGN,
        (),
        "feature.engraving",
        CandidateCertainty.EXPLICIT,
        "An engraving prohibition is retained without inventing a schema field.",
    ),
    (
        re.compile(
            r"\b(?:no|without)\s+(?:additional|extra|side)\s+stones?\b|"
            r"\bбез\s+(?:дополнительн\w+|боков\w+)\s+камн\w*\b",
            re.I,
        ),
        CandidateClassification.PROHIBITION,
        CandidateSubject.SIDE_STONES,
        (),
        "feature.side_stones",
        CandidateCertainty.EXPLICIT,
        "Absence of side stones cannot create or bind a side-stone group.",
    ),
    (
        re.compile(
            r"\b(?:do\s+not\s+change|keep|preserve)\s+(?:the\s+)?center\s+stone"
            r"(?:\s+exactly\s+as\s+specified)?\b|"
            r"\bне\s+менять\s+форм\w*\s+центральн\w+\s+камн\w*\b",
            re.I,
        ),
        CandidateClassification.PRESERVATION,
        CandidateSubject.CENTER_STONE,
        (),
        "component.center_stone",
        CandidateCertainty.EXPLICIT,
        "Preservation intent is evidence for later policy processing, not a value update.",
    ),
    (
        re.compile(
            r"\b(?:keep|preserve)\s+(?:the\s+)?(?:original\s+)?proportions?\b|"
            r"\b(?:сохранить|не\s+менять)\s+(?:исходн\w+\s+)?пропорци\w*\b",
            re.I,
        ),
        CandidateClassification.PRESERVATION,
        CandidateSubject.OVERALL_DESIGN,
        (),
        "design.proportions",
        CandidateCertainty.EXPLICIT,
        "Qualitative preservation intent is retained without inventing dimensions.",
    ),
    (
        re.compile(r"\b(?:keep|preserve)\s+(?:the\s+)?(?:original\s+)?(?:band|shank)\b", re.I),
        CandidateClassification.PRESERVATION,
        CandidateSubject.BAND,
        (),
        "component.band",
        CandidateCertainty.EXPLICIT,
        "Band preservation is retained without inventing or locking unspecified attributes.",
    ),
    (
        re.compile(r"\b(?:do\s+not|don't)\s+change\s+(?:that|this)\s+part\b", re.I),
        CandidateClassification.PRESERVATION,
        CandidateSubject.UNKNOWN,
        (),
        None,
        CandidateCertainty.AMBIGUOUS,
        "An unbound preservation instruction remains ambiguous and cannot create a lock.",
    ),
)

_AESTHETIC = re.compile(
    r"\b(?:elegant|delicate|light|airy|bold|vintage|modern|classic|distinctive|"
    r"элегант\w*|изящн\w*|л[её]гк\w*|воздушн\w*|винтажн\w*|современн\w*)\b",
    re.IGNORECASE,
)

_UNRESOLVED_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "be",
        "but",
        "by",
        "design",
        "for",
        "from",
        "in",
        "is",
        "it",
        "make",
        "of",
        "on",
        "only",
        "overall",
        "specified",
        "the",
        "this",
        "to",
        "use",
        "want",
        "with",
        "а",
        "без",
        "быть",
        "в",
        "дизайн",
        "должен",
        "и",
        "из",
        "на",
        "не",
        "но",
        "по",
        "с",
        "только",
        "хочу",
    }
)


def _special_constraint_candidates(text: str) -> tuple[list[dict], list[tuple[int, int]]]:
    """Existing property-bound evidence, shared with the scoped symmetry consumer."""
    candidates: list[dict] = []
    protected_spans: list[tuple[int, int]] = []
    for (
        pattern,
        classification,
        subject,
        normalized_values,
        semantic_subject,
        certainty,
        detail,
    ) in _SPECIAL_CONSTRAINTS:
        for match in pattern.finditer(text):
            # Earlier, complete constraints own their spans: an embedded positive verb in
            # "do not add a halo" is not another instruction. Separate clauses remain visible.
            if _inside_any(match.start(), match.end(), protected_spans):
                continue
            protected_spans.append(match.span())
            candidates.append(
                _structured_candidate(
                    text,
                    match.start(),
                    match.end(),
                    target=None,
                    subject=subject,
                    classification=(
                        CandidateClassification.PREFERENCE
                        if classification == CandidateClassification.REQUIREMENT
                        and _classification_for(text, match.start(), match.end())
                        == CandidateClassification.PREFERENCE
                        else classification
                    ),
                    certainty=_certainty_for(text, match.start(), match.end(), certainty),
                    raw_value=match.group(0),
                    normalized_values=normalized_values,
                    semantic_subject=semantic_subject,
                    normalization_source=NormalizationSource.DETERMINISTIC_PATTERN,
                    detail=detail,
                )
            )
    return candidates, protected_spans


def parse_full_message(
    text: str,
    *,
    locale: Literal["en", "ru"],
    dictionary: DictionaryRegistry,
    knowledge_runtime: AnyCompiledKnowledge | None = None,
) -> FullMessageParseResult:
    """Extract conservative structured evidence without changing canonical Product State."""

    if not isinstance(text, str) or not text or not text.strip():
        raise ValueError("full-message input must contain non-whitespace text")
    if len(text) > 2000:
        raise ValueError("full-message input exceeds the domain text limit")

    runtime = (
        validate_compiled_knowledge(knowledge_runtime) if knowledge_runtime is not None else None
    )
    candidates = _lexical_candidates(text, dictionary, runtime)

    from .p010_symmetry import defer_shared_negative_candidates, symmetry_evidence

    candidates.extend(symmetry_evidence(text, runtime, dictionary=dictionary))
    candidates = defer_shared_negative_candidates(text, runtime, candidates, dictionary=dictionary)

    recognized = [(item["evidence"]["start"], item["evidence"]["end"]) for item in candidates]
    candidates.extend(_unresolved_candidates(text, recognized))

    candidates = _deduplicate(candidates)
    candidates.sort(
        key=lambda item: (
            item["evidence"]["start"],
            item["evidence"]["end"],
            item["target"].value if isinstance(item.get("target"), StrEnum) else "",
            item["subject"].value,
            item["normalization_source"].value,
            item["normalized_values"],
        )
    )
    immutable = tuple(
        StructuredCandidate(candidate_id=f"candidate_{index:04d}", **item)
        for index, item in enumerate(candidates, start=1)
    )
    identity = (
        {
            "knowledge_package_id": runtime.package_id,
            "knowledge_artifact_version": runtime.artifact_version,
            "knowledge_runtime_sha256": runtime.sha256,
        }
        if runtime is not None
        else {}
    )
    return FullMessageParseResult(
        original_text=text,
        requested_locale=locale,
        detected_language=_detect_language(text),
        dictionary_artifact_version=dictionary.artifact_version,
        candidates=immutable,
        **identity,
    )


def _lexical_candidates(text: str, dictionary: DictionaryRegistry, runtime) -> list[dict]:
    """One lexical path for extraction and independent raw-text scope verification."""
    surfaces = _dictionary_surfaces(dictionary)
    if runtime is not None:
        surfaces.extend(_knowledge_surfaces(runtime))
    candidates, protected_spans = _special_constraint_candidates(text)
    found = _mark_choice_ambiguity(text, _find_surfaces(text, surfaces))
    for item in found:
        if not _inside_any(item.start, item.end, protected_spans):
            candidates.append(_candidate_from_surface(text, item, dictionary, runtime, found))
    candidates.extend(_measurement_candidates(text))
    candidates.extend(_quantity_candidates(text))
    candidates.extend(_aesthetic_candidates(text, protected_spans))
    return candidates


def _dictionary_surfaces(dictionary: DictionaryRegistry) -> list[_Surface]:
    surfaces = []
    for domain_id in dictionary:
        entry = dictionary[domain_id]
        for locale in (DictionaryLocale.EN, DictionaryLocale.RU):
            terms = (
                entry.canonical_terms.for_locale(locale),
                *entry.synonyms.for_locale(locale),
                *(alias.term for alias in entry.deprecated_aliases if alias.locale == locale),
            )
            surfaces.extend(
                _Surface(
                    text=term,
                    locale=locale.value,
                    category=entry.category,
                    normalized_id=domain_id,
                    source=NormalizationSource.DOMAIN_DICTIONARY,
                )
                for term in terms
            )
            if entry.category == DictionaryCategory.STONE_SHAPE and locale == DictionaryLocale.RU:
                for term in terms:
                    words = _tokens(term)
                    if len(words) > 1:
                        surfaces.append(
                            _Surface(
                                text=words[0].text,
                                locale=locale.value,
                                category=entry.category,
                                normalized_id=domain_id,
                                source=NormalizationSource.DOMAIN_DICTIONARY,
                            )
                        )
    return surfaces


def _knowledge_surfaces(runtime: AnyCompiledKnowledge) -> list[_Surface]:
    kinds = {item.concept_id: item.kind for item in runtime.domain_knowledge}
    surfaces = []
    for mapping in runtime.language_mappings:
        category = _KIND_TO_CATEGORY.get(kinds.get(mapping.concept_id, ""))
        for term in (mapping.canonical_term, *mapping.aliases):
            surfaces.append(
                _Surface(
                    text=term,
                    locale=mapping.locale,
                    category=category,
                    normalized_id=mapping.concept_id,
                    source=NormalizationSource.KNOWLEDGE_LIBRARY,
                    kind=kinds.get(mapping.concept_id),
                )
            )
    return surfaces


def _tokens(text: str) -> tuple[_Token, ...]:
    return tuple(
        _Token(match.group(0), match.start(), match.end()) for match in _TOKEN.finditer(text)
    )


def _surface_key(value: str, locale: str) -> str:
    normalized = (
        normalize_knowledge_text(value).replace("ё", "е").replace("-", " ").replace("‑", " ")
    )
    if locale == "ru":
        return ru_morphology_key(normalized).replace("ё", "е")
    words = normalized.split()
    if len(words) == 1 and len(normalized) > 4 and normalized.endswith("s"):
        return normalized[:-1]
    return normalized


def _find_surfaces(text: str, surfaces: list[_Surface]) -> list[_Found]:
    tokens = _tokens(text)
    indexed: dict[tuple[str, str], list[_Surface]] = {}
    max_words = 1
    for surface in surfaces:
        key = _surface_key(surface.text, surface.locale)
        indexed.setdefault((surface.locale, key), []).append(surface)
        max_words = max(max_words, len(_tokens(surface.text)))

    found = []
    for start in range(len(tokens)):
        for size in range(1, min(max_words, len(tokens) - start) + 1):
            end = start + size
            phrase = text[tokens[start].start : tokens[end - 1].end]
            for language in ("en", "ru"):
                for surface in indexed.get((language, _surface_key(phrase, language)), ()):
                    found.append(_Found(tokens[start].start, tokens[end - 1].end, surface))

    unique = {
        (
            item.start,
            item.end,
            item.surface.source,
            item.surface.category,
            item.surface.normalized_id,
        ): item
        for item in found
    }
    ordered = sorted(unique.values(), key=lambda item: (item.start, -(item.end - item.start)))
    kept: list[_Found] = []
    for item in ordered:
        # Longest-span selection is local to each authority source. Knowledge
        # recognition must neither replace nor suppress supported Dictionary facts.
        if any(
            existing.surface.source == item.surface.source
            and not (
                existing.surface.category == DictionaryCategory.METAL_COLOR
                and item.surface.category == DictionaryCategory.METAL_MATERIAL
            )
            and existing.start <= item.start
            and existing.end >= item.end
            for existing in kept
        ):
            continue
        kept.append(item)
    return kept


def _mark_choice_ambiguity(text: str, found: list[_Found]) -> list[_Found]:
    alternatives: dict[tuple[int, int, NormalizationSource, DictionaryCategory, str], set[str]] = {}
    for index, left in enumerate(found):
        for right in found[index + 1 :]:
            if (
                left.surface.source != right.surface.source
                or left.surface.category != right.surface.category
                or left.surface.normalized_id == right.surface.normalized_id
                or right.start - left.end > 30
            ):
                continue
            between = text[left.end : right.start]
            if _sentence_bounds(text, left.start, left.end)[1] < right.start:
                continue
            if any(left.end <= a and b <= right.start for a, b in _assertion_breaks(text)):
                continue
            if _AMBIGUITY.search(between):
                left_key = (
                    left.start,
                    left.end,
                    left.surface.source,
                    left.surface.category,
                    left.surface.normalized_id,
                )
                right_key = (
                    right.start,
                    right.end,
                    right.surface.source,
                    right.surface.category,
                    right.surface.normalized_id,
                )
                pair = {left.surface.normalized_id, right.surface.normalized_id}
                alternatives.setdefault(left_key, set()).update(pair)
                alternatives.setdefault(right_key, set()).update(pair)
    result = []
    for item in found:
        key = (
            item.start,
            item.end,
            item.surface.source,
            item.surface.category,
            item.surface.normalized_id,
        )
        values = alternatives.get(key)
        result.append(
            replace(
                item,
                certainty=CandidateCertainty.AMBIGUOUS,
                normalized_values=tuple(sorted(values)),
            )
            if values
            else item
        )
    return result


def _candidate_from_surface(
    text: str,
    item: _Found,
    dictionary: DictionaryRegistry,
    runtime: AnyCompiledKnowledge | None,
    found: list[_Found],
) -> dict:
    evidence = text[item.start : item.end]
    subject, owner_detail = _owner_for(text, item.start, item.end, item.surface.category)
    certainty = _certainty_for(text, item.start, item.end, item.certainty)
    normalized_values = item.normalized_values or (item.surface.normalized_id,)
    source = item.surface.source
    detail = None
    candidate_term = evidence

    if source == NormalizationSource.DOMAIN_DICTIONARY:
        match = dictionary.normalize(
            evidence,
            locale=item.surface.locale,
            category=item.surface.category,
        )
        if isinstance(match, AmbiguousMatch):
            certainty = CandidateCertainty.AMBIGUOUS
            normalized_values = tuple(candidate.domain_id for candidate in match.candidates)
        elif isinstance(match, ResolvedMatch):
            normalized_values = (match.candidate.domain_id,)
        else:
            entry = dictionary[item.surface.normalized_id]
            candidate_term = entry.canonical_terms.for_locale(DictionaryLocale(item.surface.locale))
    elif runtime is not None:
        match = KnowledgeLibraryMatcher(runtime).match(evidence, locale=item.surface.locale)
        if isinstance(match, AmbiguousKnowledgeMatch):
            certainty = CandidateCertainty.AMBIGUOUS
            normalized_values = tuple(candidate.concept_id for candidate in match.candidates)
        elif isinstance(match, ResolvedKnowledgeMatch):
            normalized_values = (match.candidate.concept_id,)
            if match.candidate.mapping_mode == MappingMode.AMBIGUOUS:
                certainty = CandidateCertainty.AMBIGUOUS

    classification = _classification_for(text, item.start, item.end)
    target = _target_for(item.surface.category, subject)
    parser_target = _parser_target(target)
    application = CandidateApplication.STRUCTURED_EVIDENCE_ONLY
    parser_update = None

    owner_left, owner_right, owner_anchors = _ownership_context(text, item.start, item.end)
    component_setting = (
        item.surface.category == DictionaryCategory.STONE_SETTING
        and evidence.casefold() in {"prongs", "prong", "крапаны", "крапанах"}
        # A named stone still owns its setting independently of prong metal.
        and not any(
            owner_left <= a
            and b <= owner_right
            and owner in {CandidateSubject.CENTER_STONE, CandidateSubject.SIDE_STONES}
            for a, b, owner, _ in owner_anchors
        )
        and any(
            owner_left <= other.start
            and other.end <= owner_right
            and other.surface.category
            in {DictionaryCategory.METAL_MATERIAL, DictionaryCategory.METAL_COLOR}
            and _subject_for(text, other.start, other.end, other.surface.category)
            == CandidateSubject.PRONGS
            for other in found
        )
    )
    if component_setting:
        subject, target, parser_target = CandidateSubject.PRONGS, None, None
        detail = "Component-specific prong metal does not establish a center-stone setting."
    elif (
        item.surface.category in {DictionaryCategory.METAL_MATERIAL, DictionaryCategory.METAL_COLOR}
        and subject != CandidateSubject.PRODUCT_BODY
    ):
        detail = (
            f"Component-specific {owner_detail} metal has no approved stable component binding."
        )
    elif target in {
        StructuredTarget.SIDE_STONE_MATERIAL,
        StructuredTarget.SIDE_STONE_SHAPE,
        StructuredTarget.SIDE_STONE_CUT,
        StructuredTarget.SIDE_STONE_SETTING,
    }:
        detail = "A stable existing side-stone group_id is required before application."
    elif classification == CandidateClassification.PROHIBITION:
        detail = "A prohibition is retained as constraint evidence, not a positive value update."
    elif certainty != CandidateCertainty.EXPLICIT:
        detail = "Ambiguous alternatives require later clarification."
    elif source == NormalizationSource.KNOWLEDGE_LIBRARY:
        detail = (
            "Knowledge terminology recognition remains structured evidence until an approved "
            "Matrix binding produces a valid parser proposal. "
            f"Recognized kind: {item.surface.kind}."
        )
    elif parser_target is not None:
        value = (
            StyleTermsCandidate(terms=(candidate_term,))
            if parser_target == ParserTarget.STYLE
            else TermCandidate(text=candidate_term)
        )
        parser_update = CandidateUpdate(target=parser_target, value=value)
        application = CandidateApplication.PARSER_CANDIDATE_READY
    else:
        detail = "The current ParserCandidate contract cannot apply this relationship directly."

    return _structured_candidate(
        text,
        item.start,
        item.end,
        target=target,
        subject=subject,
        classification=classification,
        certainty=certainty,
        raw_value=evidence,
        normalized_values=normalized_values,
        normalization_source=source,
        application=application,
        parser_update=parser_update,
        detail=detail,
    )


def _classification_for(text: str, start: int, end: int) -> CandidateClassification:
    left, right = _intent_bounds(text, start, end)
    context = text[left:end]
    if _NEGATION.search(_TENTATIVE.sub("", context)) or _REJECTED_ASSERTION.search(text[end:right]):
        return CandidateClassification.PROHIBITION
    if _PREFERENCE.search(context):
        return CandidateClassification.PREFERENCE
    return CandidateClassification.REQUIREMENT


def _certainty_for(text, start, end, current):
    left, right = _intent_bounds(text, start, end)
    if _TENTATIVE.search(text[left:right]):
        return CandidateCertainty.AMBIGUOUS
    # Commas cannot close a qualifier or prove that its bare list continuation
    # is an independent assertion. A sentence or explicit contrast can.
    sentence_start, sentence_end = _sentence_bounds(text, start, end)
    for _, boundary_end in _assertion_breaks(text):
        if sentence_start < boundary_end <= left:
            sentence_start = boundary_end
    prefix = text[sentence_start:left]
    qualifier = tuple(_TENTATIVE.finditer(prefix))
    if qualifier and not _CONTRAST.search(prefix, qualifier[-1].end()):
        return CandidateCertainty.AMBIGUOUS
    # A standalone trailing hedge belongs to this assertion, not the next object.
    tail = text[right:sentence_end].strip()
    if tail.startswith(",") and _TENTATIVE.fullmatch(tail[1:].strip()):
        return CandidateCertainty.AMBIGUOUS
    return current


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    # Reuse the existing offset-preserving, decimal-aware scope primitive.
    from .p010_symmetry import _bounds

    return _bounds(text, start, end, ".!?;")


def _intent_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    from .p010_symmetry import _bounds

    left, right = _bounds(text, start, end, ".!?;,—–")
    for boundary_start, boundary_end in _assertion_breaks(text):
        if left <= boundary_start and boundary_end <= start:
            left = boundary_end
        elif end <= boundary_start < right:
            right = boundary_start
            break
    return left, right


def _assertion_breaks(text: str) -> tuple[tuple[int, int], ...]:
    """Original-offset boundaries proved by a new governor, not by 'and' alone.

    A coordinated bare object retains its shared prefix/postfix predicate. A
    fresh request, rejection or qualifier governs its own assertion instead.
    The negative-list and ownership consumers must use the same boundary proof.
    This classifies evidence only; it cannot select a canonical conflict winner.
    """
    boundaries = [match.span() for match in _CONTRAST.finditer(text)]
    for match in _COORDINATION.finditer(text):
        left, right = _sentence_bounds(text, match.start(), match.end())
        before, after = text[left : match.start()], text[match.end() : right].lstrip()
        if _REQUEST_START.match(after) or _NEGATION.match(after) or _TENTATIVE.match(after):
            boundaries.append(match.span())
        elif (
            _REQUEST_START.search(before)
            and not _NEGATION.search(before)
            and _REJECTED_ASSERTION.search(after)
        ):
            # 'I want gold and platinum is not what I want' has two predicates;
            # 'gold and platinum is not what I want' has one shared predicate.
            boundaries.append(match.span())
    return tuple(sorted(set(boundaries)))


# Nominal ownership is independent of intent: an object list can share polarity
# while naming different owners. No stable IDs or new public subject types here.
_OBJECT_JOIN = re.compile(r"\b(?:with|and|и|с|со)\b", re.I)
_PRODUCT_NOUN = re.compile(
    r"\b(?:ring(?![- ]shaped)|pendant|jewel(?:ry|lery)|body|кольц\w*|подвес\w*|издели\w*)\b", re.I
)
_UNREPRESENTED_COMPONENT = re.compile(
    r"\b(?:head|basket|gallery|shoulders?|coating|plating|plated|colou?red|головк\w*|каст\w*|корзин\w*|галере\w*|плеч\w*)\b",
    re.I,
)
_STONE_NOUN = re.compile(
    r"\b(?:stones?|gems?|diamond\w*|emerald\w*|sapphire\w*|кам\w*|алмаз\w*|бриллиант\w*|изумруд\w*|сапфир\w*)\b",
    re.I,
)
_BODY_METAL = re.compile(r"\b(?:metal|gold|platinum|металл\w*|золот\w*|платин\w*)\b", re.I)


def _ownership_context(text, start, end):
    left, right = _intent_bounds(text, start, end)
    anchors = []
    for subject, pattern in _SUBJECT_PATTERNS.items():
        for match in pattern.finditer(text, left, right):
            if (
                subject == CandidateSubject.BAND
                and re.search(r"(?:split[- ]|раздвоенн\w*\s+)$", text[left : match.start()], re.I)
                and _PRODUCT_NOUN.match(text[match.end() : right].lstrip())
            ):
                continue  # A construction adjective is not a metal component.
            anchors.append((match.start(), match.end(), subject, match.group()))
    anchors.extend(
        (m.start(), m.end(), CandidateSubject.PRODUCT_BODY, m.group())
        for m in _PRODUCT_NOUN.finditer(text, left, right)
    )
    anchors.extend(
        (m.start(), m.end(), CandidateSubject.UNKNOWN, m.group())
        for m in _UNREPRESENTED_COMPONENT.finditer(text, left, right)
    )
    # A bare gemstone noun proves a stone relationship, not a canonical material.
    # Explicit side/center anchors always take precedence over this fallback.
    if not any(
        a[2] in {CandidateSubject.CENTER_STONE, CandidateSubject.SIDE_STONES} for a in anchors
    ):
        anchors.extend(
            (m.start(), m.end(), CandidateSubject.CENTER_STONE, m.group())
            for m in _STONE_NOUN.finditer(text, left, right)
        )
    for match in re.compile(
        r"\b(?:style|appearance|look|design|стиль|облик|дизайн)\b", re.I
    ).finditer(text, left, right):
        if match.group().casefold() == "design" and text[
            left : match.start()
        ].strip().casefold() in {"", "please"}:
            continue  # Imperative "Design ..." is not an object owning later properties.
        anchors.append((match.start(), match.end(), CandidateSubject.OVERALL_DESIGN, match.group()))
    joins = tuple(_OBJECT_JOIN.finditer(text, left, right))
    for join in joins:
        before = any(left <= a and b <= join.start() for a, b, _, _ in anchors)
        # An owner's coordinated modifiers may contain another conjunction:
        # "with white and yellow gold prongs" still names one component.
        # Only a preceding owner makes a later join separate another object.
        after = any(join.end() <= a and b <= right for a, b, _, _ in anchors)
        if after and (before or join.group().casefold() in {"with", "с", "со"}):
            if join.end() <= start:
                left = join.end()
            elif end <= join.start():
                right = join.start()
                break
    return left, right, anchors


def _owner_for(text, start, end, category):
    if category == DictionaryCategory.JEWELRY_TYPE:
        return CandidateSubject.PRODUCT, "product"
    left, right, anchors = _ownership_context(text, start, end)
    candidates = []
    stone = category in {
        DictionaryCategory.GEMSTONE_MATERIAL,
        DictionaryCategory.STONE_SHAPE,
        DictionaryCategory.STONE_CUT,
        DictionaryCategory.STONE_SETTING,
    }
    metal = category in {
        DictionaryCategory.METAL_MATERIAL,
        DictionaryCategory.METAL_COLOR,
        DictionaryCategory.METAL_PURITY,
    }
    for a, b, subject, label in anchors:
        if a < left or b > right:
            continue
        if a >= end and _NEGATION.search(text[end:a]):
            continue
        if metal and subject in {
            CandidateSubject.CENTER_STONE,
            CandidateSubject.SIDE_STONES,
            CandidateSubject.OVERALL_DESIGN,
        }:
            continue
        if stone and subject in {
            CandidateSubject.PRODUCT_BODY,
            CandidateSubject.OVERALL_DESIGN,
            CandidateSubject.SETTING,
        }:
            continue
        if category == DictionaryCategory.STONE_SETTING and subject == CandidateSubject.PRONGS:
            continue  # Explicit setting vocabulary is handled independently.
        distance = min(abs(a - end), abs(start - b))
        candidates.append((distance, subject.value, subject, label))
    if candidates:
        _, _, subject, label = min(candidates)
        if category == DictionaryCategory.STYLE and subject == CandidateSubject.PRODUCT_BODY:
            subject = CandidateSubject.OVERALL_DESIGN
        if category == DictionaryCategory.CONSTRUCTION:
            subject = CandidateSubject.PRODUCT
        return subject, label
    if metal:
        return CandidateSubject.PRODUCT_BODY, "product body"
    if stone:
        return CandidateSubject.CENTER_STONE, "center stone"
    if category == DictionaryCategory.STYLE:
        return CandidateSubject.OVERALL_DESIGN, "overall design"
    if category == DictionaryCategory.CONSTRUCTION:
        return CandidateSubject.PRODUCT, "construction"
    if _STONE_NOUN.search(text[left:right]):
        return CandidateSubject.CENTER_STONE, "stone"
    if _BODY_METAL.search(text[left:right]):
        return CandidateSubject.PRODUCT_BODY, "product body"
    return CandidateSubject.UNKNOWN, "unresolved owner"


def _subject_for(text, start, end, category):
    return _owner_for(text, start, end, category)[0]


def _target_for(
    category: DictionaryCategory,
    subject: CandidateSubject,
) -> StructuredTarget | None:
    if category == DictionaryCategory.JEWELRY_TYPE:
        return StructuredTarget.JEWELRY_TYPE
    if category == DictionaryCategory.METAL_MATERIAL:
        return StructuredTarget.METAL_MATERIAL if subject == CandidateSubject.PRODUCT_BODY else None
    if category == DictionaryCategory.METAL_COLOR:
        return StructuredTarget.METAL_COLOR if subject == CandidateSubject.PRODUCT_BODY else None
    if category == DictionaryCategory.STYLE:
        return StructuredTarget.STYLE if subject == CandidateSubject.OVERALL_DESIGN else None
    if subject not in {CandidateSubject.CENTER_STONE, CandidateSubject.SIDE_STONES}:
        return None
    side = subject == CandidateSubject.SIDE_STONES
    return {
        DictionaryCategory.GEMSTONE_MATERIAL: (
            StructuredTarget.SIDE_STONE_MATERIAL if side else StructuredTarget.CENTER_STONE_MATERIAL
        ),
        DictionaryCategory.STONE_SHAPE: (
            StructuredTarget.SIDE_STONE_SHAPE if side else StructuredTarget.CENTER_STONE_SHAPE
        ),
        DictionaryCategory.STONE_CUT: (
            StructuredTarget.SIDE_STONE_CUT if side else StructuredTarget.CENTER_STONE_CUT
        ),
        DictionaryCategory.STONE_SETTING: (
            StructuredTarget.SIDE_STONE_SETTING if side else StructuredTarget.CENTER_STONE_SETTING
        ),
    }.get(category)


def _parser_target(target: StructuredTarget | None) -> ParserTarget | None:
    if target is None:
        return None
    try:
        return ParserTarget(target.value)
    except ValueError:
        return None


def _measurement_candidates(text: str) -> list[dict]:
    candidates = []
    dimensions_pattern = re.compile(
        r"(?P<a>\d+(?:[.,]\d+)?)\s*[x×х]\s*(?P<b>\d+(?:[.,]\d+)?)\s*[x×х]\s*"
        r"(?P<c>\d+(?:[.,]\d+)?)\s*(?:mm|мм)\b",
        re.I,
    )
    occupied = []
    for match in dimensions_pattern.finditer(text):
        occupied.append(match.span())
        subject = _subject_for(text, match.start(), match.end(), DictionaryCategory.STONE_SHAPE)
        target = (
            StructuredTarget.SIDE_STONE_DIMENSIONS
            if subject == CandidateSubject.SIDE_STONES
            else (
                StructuredTarget.CENTER_STONE_DIMENSIONS
                if subject == CandidateSubject.CENTER_STONE
                else None
            )
        )
        values = tuple(float(match.group(key).replace(",", ".")) for key in ("a", "b", "c"))
        update = None
        application = CandidateApplication.STRUCTURED_EVIDENCE_ONLY
        detail = (
            "A stable existing side-stone group_id is required before application."
            if subject == CandidateSubject.SIDE_STONES
            else "Component-specific measurement has no approved parser target binding."
        )
        if subject == CandidateSubject.CENTER_STONE:
            update = CandidateUpdate(
                target=ParserTarget.CENTER_STONE_DIMENSIONS,
                value=DimensionsCandidate(
                    value={
                        "length": {"value": values[0], "unit": "mm"},
                        "width": {"value": values[1], "unit": "mm"},
                        "depth": {"value": values[2], "unit": "mm"},
                    }
                ),
            )
            application = CandidateApplication.PARSER_CANDIDATE_READY
            detail = None
        candidates.append(
            _structured_candidate(
                text,
                match.start(),
                match.end(),
                target=target,
                subject=subject,
                classification=_classification_for(text, match.start(), match.end()),
                certainty=CandidateCertainty.EXPLICIT,
                raw_value={
                    "length": values[0],
                    "width": values[1],
                    "depth": values[2],
                    "unit": "mm",
                },
                normalization_source=NormalizationSource.DETERMINISTIC_PATTERN,
                application=application,
                parser_update=update,
                detail=detail,
            )
        )

    weight_pattern = re.compile(r"\b(?P<value>\d+(?:[.,]\d+)?)\s*(?:ct|carats?|карат\w*)\b", re.I)
    for match in weight_pattern.finditer(text):
        if _inside_any(match.start(), match.end(), occupied):
            continue
        value = float(match.group("value").replace(",", "."))
        subject = _subject_for(text, match.start(), match.end(), DictionaryCategory.STONE_SHAPE)
        target = (
            StructuredTarget.SIDE_STONE_WEIGHT
            if subject == CandidateSubject.SIDE_STONES
            else (
                StructuredTarget.CENTER_STONE_WEIGHT
                if subject == CandidateSubject.CENTER_STONE
                else None
            )
        )
        update = None
        application = CandidateApplication.STRUCTURED_EVIDENCE_ONLY
        detail = (
            "A stable existing side-stone group_id is required before application."
            if subject == CandidateSubject.SIDE_STONES
            else "Component-specific measurement has no approved parser target binding."
        )
        if subject == CandidateSubject.CENTER_STONE:
            update = CandidateUpdate(
                target=ParserTarget.CENTER_STONE_WEIGHT,
                value=WeightCandidate(value={"value": value, "unit": "ct"}),
            )
            application = CandidateApplication.PARSER_CANDIDATE_READY
            detail = None
        candidates.append(
            _structured_candidate(
                text,
                match.start(),
                match.end(),
                target=target,
                subject=subject,
                classification=_classification_for(text, match.start(), match.end()),
                certainty=CandidateCertainty.EXPLICIT,
                raw_value={"value": value, "unit": "ct"},
                normalization_source=NormalizationSource.DETERMINISTIC_PATTERN,
                application=application,
                parser_update=update,
                detail=detail,
            )
        )
    return candidates


def _quantity_candidates(text: str) -> list[dict]:
    pattern = re.compile(
        r"\b(?P<number>two|three|four|2|3|4|двумя|два|две|тремя|три|четырьмя|четыре)\b"
        r"(?P<context>.{0,35}?)(?:side[\s-]*(?:stones?|diamonds?)|diamonds?\s+on\s+the\s+sides?|"
        r"бриллиант\w*\s+по\s+бокам|камн\w*\s+по\s+бокам)",
        re.I,
    )
    values = {
        "two": 2,
        "2": 2,
        "двумя": 2,
        "два": 2,
        "две": 2,
        "three": 3,
        "3": 3,
        "тремя": 3,
        "три": 3,
        "four": 4,
        "4": 4,
        "четырьмя": 4,
        "четыре": 4,
    }
    candidates = []
    for match in pattern.finditer(text):
        value = values[match.group("number").casefold()]
        scope = (
            "per_side"
            if re.search(r"each\s+side|кажд\w+\s+сторон", match.group(0), re.I)
            else "per_item"
        )
        candidates.append(
            _structured_candidate(
                text,
                match.start("number"),
                match.end("number"),
                target=StructuredTarget.SIDE_STONE_QUANTITY,
                subject=CandidateSubject.SIDE_STONES,
                classification=_classification_for(text, match.start(), match.end()),
                certainty=CandidateCertainty.EXPLICIT,
                raw_value={"value": value, "scope": scope},
                normalization_source=NormalizationSource.DETERMINISTIC_PATTERN,
                application=CandidateApplication.STRUCTURED_EVIDENCE_ONLY,
                detail="A stable existing side-stone group_id is required before application.",
            )
        )
    return candidates


def _aesthetic_candidates(text: str, protected: list[tuple[int, int]]) -> list[dict]:
    candidates = []
    for match in _AESTHETIC.finditer(text):
        if _inside_any(match.start(), match.end(), protected):
            continue
        subject = _subject_for(text, match.start(), match.end(), DictionaryCategory.STYLE)
        classification = _classification_for(text, match.start(), match.end())
        candidates.append(
            _structured_candidate(
                text,
                match.start(),
                match.end(),
                target=_target_for(DictionaryCategory.STYLE, subject),
                subject=subject,
                classification=(
                    CandidateClassification.PROHIBITION
                    if classification == CandidateClassification.PROHIBITION
                    else CandidateClassification.PREFERENCE
                ),
                certainty=CandidateCertainty.UNRESOLVED,
                raw_value=match.group(0),
                normalization_source=NormalizationSource.NONE,
                application=CandidateApplication.STRUCTURED_EVIDENCE_ONLY,
                detail="Aesthetic wording is preserved because it is outside reviewed vocabulary.",
            )
        )
    return candidates


_OWNER_WORD = re.compile(
    r"(?:center|central|centre|stone|stones|side|sides|prong|prongs|shank|band|head|basket|gallery|shoulder|shoulders|style|appearance|look|"
    r"центральн\w*|боков\w*|крапан\w*|шинк\w*|камн\w*|камень|головк\w*|корзин\w*|галере\w*|плеч\w*|стиль)",
    re.I,
)


def _unresolved_candidates(text: str, recognized: list[tuple[int, int]]) -> list[dict]:
    candidates = []
    for token in _tokens(text):
        normalized = normalize_knowledge_text(token.text).replace("ё", "е")
        owner_left, owner_right, _ = _ownership_context(text, token.start, token.end)
        if (
            len(normalized) < 3
            or normalized in _UNRESOLVED_STOPWORDS
            or (
                _OWNER_WORD.fullmatch(token.text)
                and any(owner_left <= a and b <= owner_right for a, b in recognized)
            )
            or normalized.isdigit()
            or _inside_any(token.start, token.end, recognized)
        ):
            continue
        candidates.append(
            _structured_candidate(
                text,
                token.start,
                token.end,
                target=None,
                subject=_subject_for(text, token.start, token.end, None),
                classification=_classification_for(text, token.start, token.end),
                certainty=CandidateCertainty.UNRESOLVED,
                raw_value=token.text,
                normalization_source=NormalizationSource.NONE,
                application=CandidateApplication.STRUCTURED_EVIDENCE_ONLY,
                detail="Unrecognized wording is retained for later clarification.",
            )
        )
    return candidates


def _structured_candidate(
    text: str,
    start: int,
    end: int,
    *,
    target: StructuredTarget | None,
    subject: CandidateSubject,
    classification: CandidateClassification,
    certainty: CandidateCertainty,
    raw_value: JsonValue,
    normalized_values: tuple[str, ...] = (),
    semantic_subject: str | None = None,
    normalization_source: NormalizationSource,
    application: CandidateApplication = CandidateApplication.STRUCTURED_EVIDENCE_ONLY,
    parser_update: CandidateUpdate | None = None,
    detail: str | None,
) -> dict:
    if certainty == CandidateCertainty.EXPLICIT:
        certainty = _certainty_for(text, start, end, certainty)
    if (
        classification
        in {CandidateClassification.PROHIBITION, CandidateClassification.PRESERVATION}
        or certainty != CandidateCertainty.EXPLICIT
    ):
        parser_update = None
        application = CandidateApplication.STRUCTURED_EVIDENCE_ONLY
    return {
        "target": target,
        "subject": subject,
        "classification": classification,
        "certainty": certainty,
        "evidence": {"start": start, "end": end, "text": text[start:end]},
        "raw_value": raw_value,
        "normalized_values": normalized_values,
        "semantic_subject": semantic_subject,
        "normalization_source": normalization_source,
        "application": application,
        "parser_update": parser_update,
        "detail": detail,
    }


def _deduplicate(candidates: list[dict]) -> list[dict]:
    unique = {}
    for item in candidates:
        update = item.get("parser_update")
        key = (
            item["evidence"]["start"],
            item["evidence"]["end"],
            item.get("target"),
            item.get("semantic_subject"),
            item["subject"],
            item["classification"],
            item["normalization_source"],
            item["normalized_values"],
            update.target if update is not None else None,
        )
        unique.setdefault(key, item)
    return list(unique.values())


def _inside_any(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(span_start <= start and end <= span_end for span_start, span_end in spans)


def _detect_language(text: str) -> MessageLanguage:
    has_ru = any("а" <= char.casefold() <= "я" or char.casefold() == "ё" for char in text)
    has_en = any("a" <= char.casefold() <= "z" for char in text)
    if has_ru and has_en:
        return MessageLanguage.MIXED
    if has_ru:
        return MessageLanguage.RU
    if has_en:
        return MessageLanguage.EN
    return MessageLanguage.UNDETERMINED
