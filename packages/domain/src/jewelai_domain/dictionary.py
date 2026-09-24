"""Versioned, deterministic domain vocabulary and normalization."""

import json
import unicodedata
from collections.abc import Iterator, Mapping
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from pydantic import Field, model_validator

from .models import DomainId, ImmutableModel, Text, Version

DICTIONARY_SCHEMA_VERSION = "1.0.0"


class DictionaryCategory(StrEnum):
    JEWELRY_TYPE = "jewelry_type"
    GEMSTONE_MATERIAL = "gemstone_material"
    STONE_SHAPE = "stone_shape"
    STONE_CUT = "stone_cut"
    STONE_SETTING = "stone_setting"
    METAL_MATERIAL = "metal_material"
    METAL_COLOR = "metal_color"
    METAL_PURITY = "metal_purity"
    CONSTRUCTION = "construction"
    STYLE = "style"


class DictionaryLocale(StrEnum):
    EN = "en"
    RU = "ru"


class ReviewStatus(StrEnum):
    PROPOSED = "proposed_pending_domain_review"
    REVIEWED = "reviewed"


class EntryLifecycle(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class MatchKind(StrEnum):
    CANONICAL = "canonical"
    SYNONYM = "synonym"
    DEPRECATED_ALIAS = "deprecated_alias"


def normalize_dictionary_text(value: str) -> str:
    """Apply bounded normalization: NFKC, case-folding, and whitespace collapse only."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class LocalizedText(ImmutableModel):
    en: Text
    ru: Text

    def for_locale(self, locale: DictionaryLocale) -> str:
        return getattr(self, locale.value)


class LocalizedSynonyms(ImmutableModel):
    en: tuple[Text, ...] = ()
    ru: tuple[Text, ...] = ()

    def for_locale(self, locale: DictionaryLocale) -> tuple[str, ...]:
        return getattr(self, locale.value)


class DeprecatedAlias(ImmutableModel):
    locale: DictionaryLocale
    term: Text


class DictionaryProvenance(ImmutableModel):
    source_kind: Literal["repository_spec"] = "repository_spec"
    source_ref: Text
    review_status: ReviewStatus


class DictionaryEntry(ImmutableModel):
    domain_id: DomainId
    category: DictionaryCategory
    canonical_terms: LocalizedText
    synonyms: LocalizedSynonyms = Field(default_factory=LocalizedSynonyms)
    definition: Text
    provenance: DictionaryProvenance
    deprecated_aliases: tuple[DeprecatedAlias, ...] = ()
    lifecycle: EntryLifecycle = EntryLifecycle.ACTIVE
    replaced_by: DomainId | None = None

    @model_validator(mode="after")
    def validate_entry(self):
        if self.lifecycle == EntryLifecycle.DEPRECATED:
            if self.replaced_by is None:
                raise ValueError("A deprecated entry must name its replacement")
            if self.replaced_by == self.domain_id:
                raise ValueError("A deprecated entry cannot replace itself")
        elif self.replaced_by is not None:
            raise ValueError("Only a deprecated entry may name a replacement")

        for locale in DictionaryLocale:
            terms = [self.canonical_terms.for_locale(locale)]
            terms.extend(self.synonyms.for_locale(locale))
            terms.extend(alias.term for alias in self.deprecated_aliases if alias.locale == locale)
            normalized = [normalize_dictionary_text(term) for term in terms]
            if "" in normalized:
                raise ValueError("Dictionary terms cannot normalize to empty text")
            if len(set(normalized)) != len(normalized):
                raise ValueError(
                    f"Entry {self.domain_id} has duplicate terms for locale {locale.value}"
                )
        return self


class DictionaryBundle(ImmutableModel):
    schema_version: Literal["1.0.0"]
    artifact_version: Version
    supported_locales: tuple[DictionaryLocale, ...] = (DictionaryLocale.EN, DictionaryLocale.RU)
    review_status: Literal["proposed_pending_domain_review"]
    source: Literal["docs/product/issues/03-dictionary.md"]
    entries: tuple[DictionaryEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_registry(self):
        if self.supported_locales != tuple(DictionaryLocale):
            raise ValueError("Dictionary v1 must declare en and ru in stable order")

        ids = [entry.domain_id for entry in self.entries]
        if len(set(ids)) != len(ids):
            raise ValueError("Dictionary domain IDs must be unique")
        expected_order = sorted(
            self.entries, key=lambda entry: (entry.category.value, entry.domain_id)
        )
        if list(self.entries) != expected_order:
            raise ValueError("Dictionary entries must use stable category and domain ID order")

        by_id = {entry.domain_id: entry for entry in self.entries}
        for entry in self.entries:
            if entry.replaced_by is not None:
                replacement = by_id.get(entry.replaced_by)
                if replacement is None:
                    raise ValueError(f"Unknown replacement ID: {entry.replaced_by}")
                if replacement.category != entry.category:
                    raise ValueError("A deprecated entry replacement must remain in its category")

        scoped_terms: dict[tuple[DictionaryCategory, DictionaryLocale, str], str] = {}
        for entry in self.entries:
            for locale in DictionaryLocale:
                terms = [entry.canonical_terms.for_locale(locale)]
                terms.extend(entry.synonyms.for_locale(locale))
                terms.extend(
                    alias.term for alias in entry.deprecated_aliases if alias.locale == locale
                )
                for term in terms:
                    key = (entry.category, locale, normalize_dictionary_text(term))
                    other = scoped_terms.get(key)
                    if other is not None and other != entry.domain_id:
                        raise ValueError(
                            "Conflicting dictionary term within category: "
                            f"{entry.category.value}/{locale.value}/{term!r}"
                        )
                    scoped_terms[key] = entry.domain_id
        return self


class MatchCandidate(ImmutableModel):
    domain_id: DomainId
    category: DictionaryCategory
    canonical_term: Text
    matched_via: MatchKind
    deprecated_input: bool
    entry_deprecated: bool
    replaced_by: DomainId | None = None


class ResolvedMatch(ImmutableModel):
    outcome: Literal["resolved"] = "resolved"
    normalized_term: str
    locale: DictionaryLocale
    candidate: MatchCandidate


class AmbiguousMatch(ImmutableModel):
    outcome: Literal["ambiguous"] = "ambiguous"
    normalized_term: str
    locale: DictionaryLocale
    candidates: tuple[MatchCandidate, ...] = Field(min_length=2)


class UnsupportedMatch(ImmutableModel):
    outcome: Literal["unsupported"] = "unsupported"
    reason: Literal["unsupported_locale", "term_not_found", "category_no_match"]
    normalized_term: str
    requested_locale: str
    locale: DictionaryLocale | None = None
    category: DictionaryCategory | None = None


type DictionaryMatch = ResolvedMatch | AmbiguousMatch | UnsupportedMatch
type _IndexedMatch = tuple[DictionaryEntry, MatchKind]


class DictionaryRegistry(Mapping[str, DictionaryEntry]):
    """Immutable registry and exact normalized-term index for one artifact version."""

    def __init__(self, bundle: DictionaryBundle):
        bundle = DictionaryBundle.model_validate(bundle)
        self._bundle = bundle
        self._entries = MappingProxyType({entry.domain_id: entry for entry in bundle.entries})
        index: dict[tuple[DictionaryLocale, str], list[_IndexedMatch]] = {}
        for entry in bundle.entries:
            for locale in DictionaryLocale:
                self._index_term(
                    index,
                    entry,
                    locale,
                    entry.canonical_terms.for_locale(locale),
                    MatchKind.CANONICAL,
                )
                for term in entry.synonyms.for_locale(locale):
                    self._index_term(index, entry, locale, term, MatchKind.SYNONYM)
            for alias in entry.deprecated_aliases:
                self._index_term(index, entry, alias.locale, alias.term, MatchKind.DEPRECATED_ALIAS)
        self._index = MappingProxyType(
            {
                key: tuple(
                    sorted(
                        matches,
                        key=lambda item: (item[0].category.value, item[0].domain_id),
                    )
                )
                for key, matches in index.items()
            }
        )

    @staticmethod
    def _index_term(index, entry, locale, term, match_kind):
        key = (locale, normalize_dictionary_text(term))
        index.setdefault(key, []).append((entry, match_kind))

    @property
    def artifact_version(self) -> str:
        return self._bundle.artifact_version

    @property
    def categories(self) -> tuple[DictionaryCategory, ...]:
        return tuple(DictionaryCategory)

    def __getitem__(self, domain_id: str) -> DictionaryEntry:
        return self._entries[domain_id]

    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    @staticmethod
    def _resolve_locale(requested_locale: str) -> DictionaryLocale | None:
        normalized = requested_locale.strip().lower().replace("_", "-")
        for candidate in (normalized, normalized.split("-", maxsplit=1)[0]):
            try:
                return DictionaryLocale(candidate)
            except ValueError:
                continue
        return None

    def normalize(
        self,
        term: str,
        *,
        locale: str,
        category: DictionaryCategory | str | None = None,
    ) -> DictionaryMatch:
        normalized_term = normalize_dictionary_text(term)
        requested_category = DictionaryCategory(category) if category is not None else None
        resolved_locale = self._resolve_locale(locale)
        if resolved_locale is None:
            return UnsupportedMatch(
                reason="unsupported_locale",
                normalized_term=normalized_term,
                requested_locale=locale,
                category=requested_category,
            )

        matches = self._index.get((resolved_locale, normalized_term), ())
        if requested_category is not None:
            matches = tuple(item for item in matches if item[0].category == requested_category)
        if not matches:
            return UnsupportedMatch(
                reason="category_no_match" if requested_category is not None else "term_not_found",
                normalized_term=normalized_term,
                requested_locale=locale,
                locale=resolved_locale,
                category=requested_category,
            )

        candidates = tuple(
            MatchCandidate(
                domain_id=entry.domain_id,
                category=entry.category,
                canonical_term=entry.canonical_terms.for_locale(resolved_locale),
                matched_via=match_kind,
                deprecated_input=match_kind == MatchKind.DEPRECATED_ALIAS,
                entry_deprecated=entry.lifecycle == EntryLifecycle.DEPRECATED,
                replaced_by=entry.replaced_by,
            )
            for entry, match_kind in matches
        )
        if len(candidates) > 1:
            return AmbiguousMatch(
                normalized_term=normalized_term,
                locale=resolved_locale,
                candidates=candidates,
            )
        return ResolvedMatch(
            normalized_term=normalized_term,
            locale=resolved_locale,
            candidate=candidates[0],
        )


def load_domain_dictionary(path: str | Path) -> DictionaryRegistry:
    """Load a complete dictionary from an explicit path."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return DictionaryRegistry(DictionaryBundle.model_validate(data))
