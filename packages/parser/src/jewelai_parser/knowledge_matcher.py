"""Deterministic Knowledge Library surface matcher with bounded RU morphology."""

import unicodedata
from collections.abc import Iterable
from enum import StrEnum
from types import MappingProxyType
from typing import Literal

from jewelai_domain.knowledge_library import (
    CompiledKnowledgeLibrary,
    CompiledLanguageMapping,
    ConceptId,
    MappingMode,
    MappingQuality,
)
from jewelai_domain.models import ImmutableModel
from pydantic import Field


class KnowledgeMatchMethod(StrEnum):
    EXACT = "EXACT"
    RU_MORPHOLOGY = "RU_MORPHOLOGY"


class KnowledgeMatchCandidate(ImmutableModel):
    mapping_id: str
    concept_id: ConceptId
    canonical_term: str
    mapping_mode: MappingMode
    mapping_quality: MappingQuality
    context: str | None
    matched_surface: str
    match_method: KnowledgeMatchMethod


class ResolvedKnowledgeMatch(ImmutableModel):
    outcome: Literal["resolved"] = "resolved"
    normalized_input: str
    locale: Literal["en", "ru"]
    candidate: KnowledgeMatchCandidate


class AmbiguousKnowledgeMatch(ImmutableModel):
    outcome: Literal["ambiguous"] = "ambiguous"
    reason: Literal["multiple_candidates", "context_required", "declared_ambiguous"]
    normalized_input: str
    locale: Literal["en", "ru"]
    candidates: tuple[KnowledgeMatchCandidate, ...] = Field(min_length=1)


class UnsupportedKnowledgeMatch(ImmutableModel):
    outcome: Literal["unsupported"] = "unsupported"
    reason: Literal[
        "unsupported_locale",
        "term_not_found",
        "scope_no_match",
        "context_no_match",
    ]
    normalized_input: str
    requested_locale: str
    locale: Literal["en", "ru"] | None = None


type KnowledgeMatch = ResolvedKnowledgeMatch | AmbiguousKnowledgeMatch | UnsupportedKnowledgeMatch
type _IndexedMapping = tuple[CompiledLanguageMapping, str]


_RU_SUFFIXES = tuple(
    sorted(
        {
            "иями",
            "ями",
            "ами",
            "ого",
            "его",
            "ому",
            "ему",
            "ыми",
            "ими",
            "ую",
            "юю",
            "ою",
            "ею",
            "ая",
            "яя",
            "ое",
            "ее",
            "ые",
            "ие",
            "ый",
            "ий",
            "ой",
            "ей",
            "ых",
            "их",
            "ым",
            "им",
            "ом",
            "ем",
            "ах",
            "ях",
            "ам",
            "ям",
            "ов",
            "ев",
            "а",
            "я",
            "ы",
            "и",
            "у",
            "ю",
            "е",
            "о",
        },
        key=lambda item: (-len(item), item),
    )
)


def normalize_knowledge_text(value: str) -> str:
    """Apply the Knowledge Library's NFKC/case-fold/whitespace normalization."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _resolve_locale(locale: str) -> Literal["en", "ru"] | None:
    normalized = locale.strip().lower().replace("_", "-")
    base = normalized.split("-", maxsplit=1)[0]
    if base in {"en", "ru"}:
        return base
    return None


def _is_cyrillic_word(token: str) -> bool:
    letters = [char for char in token if char.isalpha()]
    return bool(letters) and all("а" <= char <= "я" or char == "ё" for char in letters)


def _ru_token_key(token: str) -> str:
    if not _is_cyrillic_word(token):
        return token
    for suffix in _RU_SUFFIXES:
        if token.endswith(suffix):
            stem = token[: -len(suffix)]
            if len(stem) >= 3:
                return stem
    return token


def ru_morphology_key(value: str) -> str:
    """Return a conservative inflection key; derivational changes are intentionally excluded."""
    normalized = normalize_knowledge_text(value)
    return " ".join(_ru_token_key(token) for token in normalized.split())


class KnowledgeLibraryMatcher:
    """Immutable deterministic matcher over one compiled Knowledge Library runtime."""

    def __init__(self, runtime: CompiledKnowledgeLibrary):
        self.runtime = CompiledKnowledgeLibrary.model_validate(runtime)
        exact: dict[tuple[str, str], list[_IndexedMapping]] = {}
        morphology: dict[str, list[_IndexedMapping]] = {}
        for mapping in self.runtime.language_mappings:
            for surface in (mapping.canonical_term, *mapping.aliases):
                normalized = normalize_knowledge_text(surface)
                exact.setdefault((mapping.locale, normalized), []).append((mapping, surface))
                if mapping.locale == "ru":
                    key = ru_morphology_key(surface)
                    morphology.setdefault(key, []).append((mapping, surface))
        self._exact = MappingProxyType(
            {key: self._stable_index(value) for key, value in exact.items()}
        )
        self._morphology = MappingProxyType(
            {key: self._stable_index(value) for key, value in morphology.items()}
        )

    @staticmethod
    def _stable_index(values: list[_IndexedMapping]) -> tuple[_IndexedMapping, ...]:
        unique = {
            (mapping.mapping_id, normalize_knowledge_text(surface)): (mapping, surface)
            for mapping, surface in values
        }
        return tuple(
            sorted(
                unique.values(),
                key=lambda item: (
                    item[0].concept_id,
                    item[0].mapping_id,
                    normalize_knowledge_text(item[1]),
                ),
            )
        )

    @property
    def artifact_version(self) -> str:
        return self.runtime.artifact_version

    @property
    def runtime_sha256(self) -> str:
        return self.runtime.sha256

    def match(
        self,
        term: str,
        *,
        locale: str,
        context: str | None = None,
        allowed_concept_ids: Iterable[str] | None = None,
    ) -> KnowledgeMatch:
        normalized = normalize_knowledge_text(term)
        resolved_locale = _resolve_locale(locale)
        if resolved_locale is None:
            return UnsupportedKnowledgeMatch(
                reason="unsupported_locale",
                normalized_input=normalized,
                requested_locale=locale,
            )

        indexed = self._exact.get((resolved_locale, normalized), ())
        method = KnowledgeMatchMethod.EXACT
        if not indexed and resolved_locale == "ru":
            indexed = self._morphology.get(ru_morphology_key(term), ())
            method = KnowledgeMatchMethod.RU_MORPHOLOGY
        if not indexed:
            return UnsupportedKnowledgeMatch(
                reason="term_not_found",
                normalized_input=normalized,
                requested_locale=locale,
                locale=resolved_locale,
            )

        if allowed_concept_ids is not None:
            allowed = frozenset(allowed_concept_ids)
            indexed = tuple(item for item in indexed if item[0].concept_id in allowed)
            if not indexed:
                return UnsupportedKnowledgeMatch(
                    reason="scope_no_match",
                    normalized_input=normalized,
                    requested_locale=locale,
                    locale=resolved_locale,
                )

        context_matched = False
        if context is not None:
            normalized_context = normalize_knowledge_text(context)
            scoped = tuple(
                item
                for item in indexed
                if item[0].context is not None
                and normalize_knowledge_text(item[0].context) == normalized_context
            )
            if scoped:
                indexed = scoped
                context_matched = True
            else:
                indexed = tuple(
                    item
                    for item in indexed
                    if item[0].context is None
                    and item[0].mapping_mode in {MappingMode.DIRECT, MappingMode.INPUT_ONLY}
                )
                if not indexed:
                    return UnsupportedKnowledgeMatch(
                        reason="context_no_match",
                        normalized_input=normalized,
                        requested_locale=locale,
                        locale=resolved_locale,
                    )
        else:
            global_matches = tuple(item for item in indexed if item[0].context is None)
            if global_matches:
                indexed = global_matches

        candidates = self._candidates(indexed, method)
        if not candidates:
            return UnsupportedKnowledgeMatch(
                reason="scope_no_match",
                normalized_input=normalized,
                requested_locale=locale,
                locale=resolved_locale,
            )

        if not context_matched:
            if any(candidate.mapping_mode == MappingMode.AMBIGUOUS for candidate in candidates):
                return AmbiguousKnowledgeMatch(
                    reason="declared_ambiguous",
                    normalized_input=normalized,
                    locale=resolved_locale,
                    candidates=candidates,
                )
            if any(candidate.mapping_mode == MappingMode.CONTEXTUAL for candidate in candidates):
                return AmbiguousKnowledgeMatch(
                    reason="context_required",
                    normalized_input=normalized,
                    locale=resolved_locale,
                    candidates=candidates,
                )

        concepts = {candidate.concept_id for candidate in candidates}
        if len(concepts) > 1:
            return AmbiguousKnowledgeMatch(
                reason="multiple_candidates",
                normalized_input=normalized,
                locale=resolved_locale,
                candidates=candidates,
            )

        return ResolvedKnowledgeMatch(
            normalized_input=normalized,
            locale=resolved_locale,
            candidate=self._best_candidate(candidates),
        )

    @staticmethod
    def _candidates(
        indexed: tuple[_IndexedMapping, ...],
        method: KnowledgeMatchMethod,
    ) -> tuple[KnowledgeMatchCandidate, ...]:
        candidates = {
            mapping.mapping_id: KnowledgeMatchCandidate(
                mapping_id=mapping.mapping_id,
                concept_id=mapping.concept_id,
                canonical_term=mapping.canonical_term,
                mapping_mode=mapping.mapping_mode,
                mapping_quality=mapping.mapping_quality,
                context=mapping.context,
                matched_surface=surface,
                match_method=method,
            )
            for mapping, surface in indexed
        }
        return tuple(
            sorted(
                candidates.values(),
                key=lambda item: (item.concept_id, item.mapping_id),
            )
        )

    @staticmethod
    def _best_candidate(
        candidates: tuple[KnowledgeMatchCandidate, ...],
    ) -> KnowledgeMatchCandidate:
        mode_rank = {
            MappingMode.DIRECT: 0,
            MappingMode.INPUT_ONLY: 1,
            MappingMode.CONTEXTUAL: 2,
            MappingMode.AMBIGUOUS: 3,
        }
        quality_rank = {
            MappingQuality.EXACT: 0,
            MappingQuality.PREFERRED: 1,
            MappingQuality.CONTEXT_DEPENDENT: 2,
            MappingQuality.APPROXIMATE: 3,
            MappingQuality.NO_DIRECT_EQUIVALENT: 4,
        }
        return min(
            candidates,
            key=lambda item: (
                mode_rank[item.mapping_mode],
                quality_rank[item.mapping_quality],
                item.mapping_id,
            ),
        )
