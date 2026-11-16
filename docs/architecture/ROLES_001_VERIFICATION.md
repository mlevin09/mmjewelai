# ROLES-001 development verification (EN MASTER)

Baseline: `262acb810f81cb75e6be0fa6d26361c7cdae0fdc`. Branch: `codex/roles-001`.
Development evidence is not independent acceptance, merge or deployment.

## Input → output

| Criterion | Observed development evidence | Status |
|---|---|---|
| Original role sources retained | 15 complete mandatory documents match recorded bytes/SHA-256 | VERIFIED PASS |
| Initial import shape | 21 canonical roles; nine complete 13-section passports; 36 matching original persona excerpts; twelve without invented passports | VERIFIED PASS (SQLite/source checks) |
| Repeatable import | unchanged=21; changing one definition updates one row/revision; next identical import unchanged=21 | VERIFIED PASS |
| Corrupt import | source-hash mismatch rejected before commit; prior revision remains unchanged | VERIFIED PASS |
| Live current-definition read | new registry lookup immediately sees changed row revision/name, without app restart | VERIFIED PASS |
| Retired IDs and merged aliases | all six former IDs and merged RR IDs rejected; unallowed Studio canonical ID also rejected | VERIFIED PASS |
| Studio choices | exact nine ordered defaults; all 21 available via internal catalog reads | VERIFIED PASS |
| Human context contrast | customer/CAD Registry and draft passport context differ; conversation policy absent/null; no permissions | VERIFIED PASS |
| Session lifecycle | customer EN and CAD RU: create → input → ask shape → oval continuation → new app/repository restore | VERIFIED PASS |
| Canonical result | emerald material retained; oval shape accepted; unspecified dimensions remain absent | VERIFIED PASS |
| CAS and tenant | stale continuation=409, revision unchanged; outsider read denied; restored design matches committed design | VERIFIED PASS |
| Invalid stored definition | 503 `role_catalog_unavailable`; synthetic sensitive marker absent; canonical revision unchanged | VERIFIED PASS |
| No runtime JSON fallback | Path reads of role seed/legacy role files forcibly blocked during fresh app startup and role/catalog reads; requests still succeed | VERIFIED PASS |
| Domain authority | current 21 roles retain LOCK/confirmation/CAS protections; shared question/rule tests | VERIFIED PASS |
| PostgreSQL migration/types/FK | dedicated test added behind unchanged disposable-container/cluster/job gate; no local Docker | SKIP / NOT VERIFIED locally |
| Shared data cleanup | none performed; NOT VALID FK preserves existing rows; downgrade refuses used/modified catalog | NO LIVE OPERATION |
| UI adaptation, live deployment, professional Knowledge activation | excluded; coordinator owns UI and release | NOT TESTED / NOT PERFORMED |

## Focused execution receipts

- Domain: `python3 -m pytest -c packages/domain/pyproject.toml packages/domain/tests/test_roles.py packages/domain/tests/test_questions.py packages/domain/tests/test_rules.py packages/domain/tests/test_questions_v2.py packages/domain/tests/test_rules_v2.py -q`: **216 PASS**, 4.00s at final shared-baseline checkpoint. Subsequent schema regeneration for current timestamps separately passed schema equality (0.88s).
- Roles HTTP/import: `python3 -m pytest -c apps/api/pyproject.toml apps/api/tests/test_current_roles.py -q`: **7 PASS**, 7.47s at final catalog checkpoint.
- Nearby API role/session/catalog slice: `test_api.py -k 'role or catalog or session or message_parser'`: nine relevant cases passed in combined receipt (combined 15 PASS, one PostgreSQL SKIP, 32 deselected; 18.18s before the final no-fallback case).
- Persistence: `test_persistence.py -k 'session or role'`: **2 PASS**, 33 deselected, 7.61s.
- Existing controlled native Prompt Enrichment lifecycle plus malformed-catalog boundary: **2 PASS**, 3.30s.
- Existing offline release verifier/mismatched-consumer boundary: **1 PASS**, 0.94s. The compiler may validate non-role artifacts without a role registry, but executable runtime composition requires one; no empty/fallback role catalog is created.
- Deterministic offline seed rebuild: byte-identical before/after; SHA-256 `f39e3e9b241b4775ebbbfe27995a6b2edbdda16c5c8c41d81c0f59cf216934d0`.
- Ruff check/format, changed-Python compilation, new documentation links and `git diff --check`: PASS.
- Alembic script graph: one head, `0021_roles_foundation`; this is NOT proof of executed PostgreSQL migration.

Development reruns followed relevant corrections only: test UUID conversion/localized dictionary
fixtures, changed shared rule baseline/schema snapshots, retired six-wording expectations,
new failure-safety checks and final catalog changes. No local full API suite or Full Regression.
Initial test failures were retained as development failures, not counted as acceptance PASS.
Mocked text-understanding provider outputs are explicitly test boundaries; no paid LLM is used.
Fresh-app restoration is executable HTTP composition over the same durable SQLite file,
not a claim of live preproduction or an independently restarted operating-system process.

## Source and release integrity

Source archive: `1L5eTL9wj1XyTwURkCFD6lVWMKsphToCY`, 238,253 bytes,
SHA-256 `a2fc0f063a07fd51299bff9368139c077fea5998d65ba7b9c2c1e8a2e1fc69bb`.
Original documents remain byte-identical in `data/roles/sources`; the separate source import
manifest records actual file hashes. Draft passport/persona maturity is never promoted.
The legacy JSON runtime file is removed; its history remains in Git. Old six-role fixtures,
policy-specific wording tests and role-pin loading expectations were intentionally replaced.
Current-session state integrity, dictionary references, provenance and authorization assertions
remain. Historical serialized user data is not rewritten or purged.

Hosted exact-head CI, including PostgreSQL execution, remains a separate recorded gate in the
Draft PR. No claim of PostgreSQL qualification is made from SQLite results or source inspection.

Original sources are stored inside the byte-identical `data/roles/sources/original-role-sources.zip`;
its import manifest identifies individual members. Original Markdown hard-break whitespace is
preserved without suppressing Git whitespace checks or changing source bytes.
