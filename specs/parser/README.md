# Parser Proposal v1.0.0

Parser Proposal is the provider-neutral acceptance boundary between an untrusted structured parsing
candidate and the immutable Jewelry Design Schema. It contains no provider SDK, network call,
extraction prompt, question selection, or Rules Engine policy.

## Trust and application boundary

A `ParserCandidate` may contain only allowlisted targets and value kinds. It cannot submit domain
state objects, provenance, confirmation, locks, derived values, assumptions, unknown values, or
inapplicability. The deterministic builder normalizes terms against the pinned Domain Dictionary and
creates only unconfirmed, unlocked `Explicit` states sourced from one supplied `MessageSource`.

A `ParserProposal` is not canonical state and is not persisted as a specification revision. The
application flow is:

```text
persisted user message → untrusted candidate → deterministic proposal → review
→ existing revision EDIT endpoint → revise_design → persistence CAS → Rules Engine
```

Proposal creation never invokes Rules Engine or Question Catalog wording. A proposal that becomes
stale is rejected by the existing revision/CAS boundary when applied.

## Supported targets

- `jewelry_type`
- `metal.material`
- `metal.color`
- `metal.purity`
- `center_stone.material`
- `center_stone.shape`
- `center_stone.cut`
- `center_stone.weight`
- `center_stone.dimensions`
- `center_stone.setting`
- `style`
- `side_stones[*].quantity` for an existing stable `group_id`

No arbitrary paths or side-stone group creation are supported. Candidate value kinds are exact
dictionary terms, Schema v1 Weight, Dimensions, purity, StoneQuantity, and a bounded tuple of style
terms. Units and quantity scope are never inferred or converted.

## Normalization and issues

Dictionary-backed targets always pass an explicit category and the session's resolved `en` or `ru`
locale. Normalization is the existing bounded Dictionary behavior—no fuzzy matching or translation.
Material `emerald` and shape `emerald_cut` remain distinct.

Stable issues are `AMBIGUOUS_TERM`, `UNSUPPORTED_TERM`, `DEPRECATED_ENTRY`,
`LOCKED_FIELD_CONFLICT`, `NOT_APPLICABLE_CONFLICT`, and `UNKNOWN_SIDE_STONE_GROUP`. Deprecated
aliases resolving to active entries use the canonical ID and emit `DEPRECATED_ALIAS_USED`.
Deprecated entries are not silently replaced. Issues leave the field unchanged and expose
deterministic candidate data where relevant.

Duplicate concrete targets fail candidate validation; “last value wins” is forbidden. Updates,
issues, and warnings use stable target/code ordering. Omitted fields remain model-equivalent. An
identical canonical value preserves its existing state, provenance, confirmation, and lock.

## Safety guarantees

Changed values are always explicit, unconfirmed, and unlocked. Different values cannot replace a
locked field; the same value preserves the locked state. Weight never implies dimensions. An emerald
plus 3 ct candidate without explicit dimensions leaves dimensions untouched. Parser output never
creates `Derived`, `Assumed`, `Unknown`, or `NotApplicable` state.

An existing `NotApplicable` state is an explicit applicability declaration. Parser Proposal v1
preserves it exactly and emits `NOT_APPLICABLE_CONFLICT` instead of converting it into a value.

The [JSON Schema](schema.json) is generated from the immutable Pydantic contract:

```sh
python -m jewelai_parser.schema specs/parser/schema.json
python -m pytest -c packages/parser/pyproject.toml packages/parser/tests -q
python -m ruff check packages/parser
python -m ruff format --check packages/parser
```

Initial terminology remains subject to the Domain Dictionary's product/jewelry review status.
