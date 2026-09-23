# Role Profiles v1.0.0

Issue #2 contract, implemented by `jewelai_domain.roles` in
[packages/domain](../../packages/domain/README.md). The [JSON Schema](schema.json) describes one
complete profile bundle, and [data/roles/v1.0.0.json](../../data/roles/v1.0.0.json) contains the six
canonical initial profiles.

## Scope and invariants

Canonical IDs are `retail_client`, `sales_manager`, `buyer`, `marketing`, `jewelry_designer`, and
`industrial_designer`. Every profile references Jewelry Design Schema `1.0.0` and the same
deterministic domain transition functions. A profile selects conversational policy only: expertise,
vocabulary, detail, question behavior, defaults, derivation, and locale handling.

`authorization_effect` is fixed to `none`. Role data cannot grant permissions, alter schema fields,
edit locked values, suppress confirmation, bypass stale-revision detection, or weaken provenance and
uncertainty requirements. Authentication, tenancy, and authorization remain outside this contract.

## Initial policy modes

| Role | Expertise | Vocabulary | Detail | Derivation |
| --- | --- | --- | --- | --- |
| retail_client | consumer | plain | essential | sourced_with_uncertainty |
| sales_manager | commercial | commercial | operational | sourced_with_uncertainty |
| buyer | procurement | specification | specification | sourced_with_uncertainty |
| marketing | marketing_communication | storytelling | communication | sourced_with_uncertainty |
| jewelry_designer | jewelry_design | professional_design | professional | sourced_with_uncertainty |
| industrial_designer | industrial_design | technical_engineering | engineering | request_exact_when_required |

All roles use deterministic rule selection and ask before assuming missing information. The question
budget is `product_review_required`, and defaults are `no_unapproved_defaults`; no numeric budget or
product default is invented. Derived values always require provenance and uncertainty. The industrial
profile requests exact measurements when required rather than treating an estimate as an exact fact.
The later Rules Engine owns actual selection, readiness, priority, and derivation decisions.

## Locale behavior

The proposed starting locale scope is `en` and `ru`, explicitly marked
`proposed_pending_domain_review`. Locale resolution is deterministic:

1. Normalize case and `_`/`-` separators.
2. Use an exact supported locale.
3. For a regional tag, use its supported base language (`ru-RU` → `ru`, `en-US` → `en`).
4. Reject the request with `UnsupportedLocaleError` if neither is supported.

There is no silent fallback from an unsupported language to arbitrary English or Russian content.
Actual translated wording belongs to the later Question Catalog.

## Loading, validation, and compatibility

Call `load_role_profiles(path)` with an explicit artifact path. Loading validates enum values, strict
unknown-field rejection, exactly one of every canonical role, canonical order, matching bundle/profile
versions, locale uniqueness, and role-specific policy combinations. Lookup rejects unknown or
non-canonical IDs with `UnknownRoleError`.

Published artifacts are immutable. Incompatible field or semantic changes require a new major schema
version. Additive changes require a new minor contract because validators reject unknown fields.
Policy changes require a new artifact version even when the schema is unchanged. Historical sessions
must pin the artifact version they used.

The initial profiles and locale scope require jewelry-domain and product review before production
publication. Exact question counts, automatic defaults, derivation thresholds, manufacturing
assumptions, and gemstone assumptions remain unresolved rather than encoded as fabricated constants.

## Verification

From the repository root in a Python 3.12+ environment:

```sh
python -m pip install -e './packages/domain[test]'
python -m pytest -c packages/domain/pyproject.toml packages/domain/tests/test_roles.py -q
python -m pytest -c packages/domain/pyproject.toml packages/domain/tests -q
python -m ruff check packages/domain
python -m ruff format --check packages/domain
```

Re-export the schema after an intentional contract change and review the diff:

```sh
python -m jewelai_domain.roles_schema specs/roles/schema.json
```
