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

## CI routing correction after first publication

Initial exact HEAD `0154dd5e797b3845e914397f7cf9fdc4121f46a6`: Domain contracts,
Web and Infrastructure passed. Runtime API #43864842724 was BLOCKED before execution,
`unmapped_impact_requires_routing_review`, selected cases=0. No PostgreSQL qualification
was obtained from that run.

The correction declares complete Domain ownership for the changed schemas/catalog/source
resources, adds a real archive-hash/deterministic-seed test, and routes the small existing
release verifier plus new fixture/builder paths. Shared helper/seed/source changes explicitly
retain Full qualification. No CI algorithms, workflows, required checks or database safety
gates are changed. Local selection preflight: blocked=[], full_required=true, 72 API targets.
Existing CI selector tests: 42 PASS (34.23s); new archive/builder proof: PASS (3.46s).
Full Regression is not dispatched. Fresh hosted CI remains an exact-new-HEAD gate, not an
inferred PASS from the previous source commit.

## Native wrapper import-path correction

On exact HEAD `530eaa1269c7a8d0fa0c59cfeeae0cddfe80640d`, disposable PostgreSQL identity,
actual migration execution and Alembic safety checks passed. Runtime collection then failed,
not tests: the native script entrypoint lacked checkout root, making `tests.current_roles`
unimportable. Local bounded RED reproduced `ModuleNotFoundError` and wrapper exitcode=2,
collected=0 on `test_parsed_enrichment.py`. API/domain test conftest now adds only the fixed
checkout root to test import paths. No production or CI algorithm change.

GREEN with the unchanged native wrapper: that API module collects 72 cases (27.27s),
`test_roles.py` collects 76 (4.06s). These are COLLECTION receipts, not execution PASS.

Unchanged native wrapper execution: EN/RU HTTP lifecycle + no-role-file-fallback: **3 PASS**,
exitcode=0, 32.49s. Only these three cases ran; no full API execution.


## Selected CI execution and migration-fixture correction

Exact HEAD `5229cd35f9f7a423bd12fc9deb87ff39a5cc4c9b`: Domain, Web and
Infrastructure passed. Runtime API #43868459903 **FAILED**: 661 PASS, 9 FAIL,
1 interrupted case, 1,385 unexecuted/incomplete out of 2,055 selected API cases;
execution hit the existing 1,200-second limit. Other selected suites were collected,
not executed. Full qualification remains required and was not dispatched.

Artifact `14228695746` (1,197,433 bytes), SHA-256
`9df8934174e37ed77c26e3080f136c2dcd2bfb4ccfe47813a68ac0792a2610ef`:

- New Roles PostgreSQL test: ValueError before migration because percent-encoded
  `%3D` is rejected by Alembic ConfigParser interpolation. Bounded local RED/GREEN
  confirms literal `=` round-trips both ConfigParser and SQLAlchemy URL parsing.
- Eight F04 PostgreSQL cases failed during their shared migration fixture setup.
  That fixture expected the earlier completion downgrade refusal. New Roles retention
  refuses first because the retained session already references RR-C25. Assertions now
  require the exact new guard and still compare retained schema/data. Existing completion
  and tombstone guard regressions invoke their specific historical guards directly,
  so the new refusal does not mask their safety assertions. Frozen migration code is unchanged.
- Add Roles retention-unit negatives and reuse the existing EN customer/RU CAD HTTP
  lifecycle on the independently verified PostgreSQL fixture. Local SQL cases still SKIP;
  only actual hosted execution can qualify their database behavior.

No production code, CI algorithm, timeout, PostgreSQL identity gate or coverage requirement
was changed in this correction. The original CI failure is retained; it is not a PASS.
