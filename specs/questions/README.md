# Question Catalog v1.0.0

Issue #4 contract, implemented by `jewelai_domain.questions` in
[packages/domain](../../packages/domain/README.md). The [JSON Schema](schema.json) describes a complete
catalog bundle, and [data/questions/v1.0.0.json](../../data/questions/v1.0.0.json) is the proposed
initial seed.

## Scope

The catalog defines what a semantic question means and how it is expressed. It never decides whether,
when, or in what order a question is asked. Selection, gap analysis, readiness, priority,
ask/derive/assume/block decisions, and question budgets belong to the later Rules Engine.

Question Catalog v1 contains five stable semantic IDs:

- `CENTER_STONE_SHAPE`
- `CENTER_STONE_DIMENSIONS`
- `CENTER_STONE_SETTING`
- `METAL_COLOR`
- `SIDE_STONE_QUANTITY`

Every entry has one canonical Schema v1 target, a structured answer contract, explicit wording for
all six canonical roles in both supported locales, examples, provenance, and review state. IDs and
meaning are stable; display wording may evolve only through a new artifact version.

## Targets and answer contracts

Targets use a bounded vocabulary rather than an arbitrary path language:

| Semantic ID | Schema target | Answer contract |
| --- | --- | --- |
| `CENTER_STONE_SHAPE` | `center_stone.shape` | `DomainId` in `stone_shape` |
| `CENTER_STONE_DIMENSIONS` | `center_stone.dimensions` | Schema v1 `Dimensions`, in mm |
| `CENTER_STONE_SETTING` | `center_stone.setting` | `DomainId` in `stone_setting` |
| `METAL_COLOR` | `metal.color` | `DomainId` in `metal_color` |
| `SIDE_STONE_QUANTITY` | `side_stones[*].quantity` | Schema v1 `StoneQuantity` |

The loader checks every target against concrete fields on `Design`, `Stone`, `Metal`, or
`SideStoneGroup`. Answer contract kinds reference the existing `DomainId`, `Dimensions`, and
`StoneQuantity` contracts; they do not redefine those values.

`side_stones[*].quantity` means the quantity field of one side-stone group selected by a later rules
or application layer. The `[*]` token is the only collection placeholder in v1. It does not select a
group, execute an expression, or embed a fixture group ID. A future Rules Engine may bind the semantic
target to a concrete stable `group_id`; that resolution is outside this catalog.

Dictionary-backed examples are validated against the pinned Domain Dictionary artifact at load time.
An example ID must exist and belong to the answer contract's category. The dimensions and quantity
examples describe value shape only; they provide no default, gemstone measurement, or inferred fact.

## Roles, locales, and rendering

Every seed question provides an explicit variant for each Role Profiles v1 ID:
`retail_client`, `sales_manager`, `buyer`, `marketing`, `jewelry_designer`, and
`industrial_designer`. There is no cross-role fallback. Unknown roles raise `UnknownRoleError`.

Each role variant requires complete `en` and `ru` text. Locale behavior delegates to the pinned Role
Profiles registry: locale tags are normalized for case and `_`/`-`, supported regional tags fall back
only to `en` or `ru`, and unrelated languages raise `UnsupportedLocaleError`. Missing translations
fail catalog validation; there is no LLM translation or silent unrelated-language fallback.

`QuestionCatalog.render(question_id, role_id, locale)` returns an immutable `RenderedQuestion` with
the semantic ID, wording, target, answer contract, resolved role and locale, and artifact version.
Unknown question IDs raise `UnknownQuestionError`. Repeated calls against the same pinned artifacts are
identical. Changing role or locale changes presentation only; semantic ID, target, answer contract,
and dictionary category remain invariant.

## Versioning and review state

The Question Catalog schema and artifact versions are independent semantic versions. The v1 artifact
pins Jewelry Design Schema, Role Profiles, and Domain Dictionary versions to `1.0.0`; load fails when
the supplied registries do not match. Published artifacts are immutable. Wording, examples, or seed
content changes require a new artifact version. Contract-incompatible changes require a new major
schema version.

All initial EN/RU wording is `proposed_pending_domain_review`. Retail phrasing, Russian jewelry
terminology, technical industrial-design wording, and whether future questions need additional
semantic granularity require product and jewelry-domain review before production publication.

## Verification

From the repository root in a Python 3.12+ environment:

```sh
python -m pip install -e './packages/domain[test]'
python -m pytest -c packages/domain/pyproject.toml packages/domain/tests/test_questions.py -q
python -m pytest -c packages/domain/pyproject.toml packages/domain/tests -q
python -m ruff check packages/domain
python -m ruff format --check packages/domain
```

Re-export the schema after an intentional contract change and review the diff:

```sh
python -m jewelai_domain.questions_schema specs/questions/schema.json
```
