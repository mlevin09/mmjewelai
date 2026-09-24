# Domain Dictionary v1.0.0

Issue #3 contract, implemented by `jewelai_domain.dictionary` in
[packages/domain](../../packages/domain/README.md). The [JSON Schema](schema.json) describes a complete
dictionary bundle, and [data/dictionary/v1.0.0.json](../../data/dictionary/v1.0.0.json) contains the
proposed initial seed.

## Scope and categories

The dictionary defines stable machine IDs and deterministic human-term normalization. It does not
select questions, make readiness decisions, parse free-form requests, grant permissions, or supply
knowledge-base facts. The v1 categories map to existing Jewelry Design Schema concepts:

- `jewelry_type`
- `gemstone_material`
- `stone_shape`
- `stone_cut`
- `stone_setting`
- `metal_material`
- `metal_color`
- `metal_purity`
- `construction`
- `style`

Every entry has a stable lower-snake-case `domain_id`, category, EN/RU canonical terms, EN/RU
synonyms, a bounded definition, provenance and review state, lifecycle status, and optional deprecated
aliases. Display wording is never the identifier. The seed is intentionally small and every entry is
marked `proposed_pending_domain_review`.

Material `emerald` and shape/cut designation `emerald_cut` are separate IDs in separate categories.
The dictionary never collapses them merely because their human wording overlaps.

## Deterministic normalization

`DictionaryRegistry.normalize` applies only these bounded string transformations:

1. Unicode NFKC normalization.
2. Unicode case-folding.
3. Leading/trailing whitespace removal and internal whitespace collapse.

It does not apply fuzzy matching, punctuation substitution, stemming, translation, or LLM inference.
Canonical terms, synonyms, and deprecated aliases use the same transformation. Repeated identical
inputs against a pinned artifact return identical results.

Locale handling matches the Role Profiles convention: `en` and `ru` are supported; case and `_`/`-`
separators are normalized; a regional tag falls back only to its base language (`ru-RU` → `ru`). An
unrelated locale is returned as an `UnsupportedMatch` with reason `unsupported_locale`; the registry
never silently switches languages.

## Outcomes, context, and collisions

Normalization returns one of three typed outcomes:

- `ResolvedMatch`: one stable ID, category, canonical term, match kind, and deprecation metadata.
- `AmbiguousMatch`: two or more sorted candidates sufficient for a clarification question.
- `UnsupportedMatch`: unsupported locale, unknown term, or no match in the requested category.

Category context filters candidates before resolution. The seed deliberately uses `halo` in both
`stone_setting` and `style`: unscoped lookup is ambiguous, while either category resolves uniquely.
Natural-language reuse across categories is valid. A normalized collision between distinct entries in
the same category and locale fails bundle validation because category context could not resolve it.
Duplicate IDs, malformed IDs, invalid categories, duplicate terms within an entry, unstable entry
order, and invalid provenance also fail closed.

Deprecated aliases remain lookup inputs but produce `matched_via=deprecated_alias` and
`deprecated_input=true`. A wholly deprecated entry must name an existing replacement in the same
category; callers can observe both lifecycle and replacement ID. Historical IDs are not silently
deleted or assigned a new meaning.

## Versioning and knowledge-base boundary

The schema and artifact versions are independent semantic versions. Published artifacts are
immutable. Policy or vocabulary changes require a new artifact version. Incompatible field/category
meaning changes require a major schema version; additive contract changes require a minor version
because older validators reject unknown fields. Historical consumers must pin their artifact version.

The dictionary defines terminology only. It contains no gemstone dimensions, weight-to-size tables,
density calculations, tolerances, proportions asserted as facts, or manufacturing estimates. Input
such as `3 ct emerald` is not parsed or converted; exact normalization returns unsupported. Sourced
quantitative estimates belong exclusively to the separate Knowledge Base.

The EN/RU translations, construction terminology, cut/shape boundaries, synonyms, and deprecated
aliases require jewelry-domain review before production publication.

## Verification

From the repository root in a Python 3.12+ environment:

```sh
python -m pip install -e './packages/domain[test]'
python -m pytest -c packages/domain/pyproject.toml packages/domain/tests/test_dictionary.py -q
python -m pytest -c packages/domain/pyproject.toml packages/domain/tests -q
python -m ruff check packages/domain
python -m ruff format --check packages/domain
```

Re-export the schema after an intentional contract change and review the diff:

```sh
python -m jewelai_domain.dictionary_schema specs/dictionary/schema.json
```
