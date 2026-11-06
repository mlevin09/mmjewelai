# Completion backend — developer evidence (not independent acceptance)

Base: `c7c81ebabbf2a257afb13599a9d90940e20b40a2`. Separate branch
`codex/smart-defaults-completion-runtime`; reviewed PR155 remains unchanged.
Final source SHA and automatic CI links are in the Draft PR. No Full Regression,
provider call, shared migration, activation, frontend edit, merge or deployment.

## Focused execution receipts

Commands use `python3 -m pytest -c <package>/pyproject.toml <explicit test files/IDs> -q`.
Each row is one local command; counts are executions, not unique coverage. Earlier
receipts are reused for unchanged boundaries; they are not called exact-final-HEAD CI.

| Receipt | Passed | Failed | Skipped | Seconds |
|---|---:|---:|---:|---:|
| sdfull-r2-green | 11 | 0 | 0 | 1.09 |
| sdfull-final-prompts | 12 | 0 | 0 | 3.02 |
| sdfull-mandatory-green | 2 | 0 | 0 | 2.58 |
| sdfull-default-off | 1 | 0 | 0 | 1.00 |
| sdfull-storage-final | 5 | 0 | 0 | 1.02 |
| sdfull-final-lifecycle | 1 | 0 | 0 | 56.45 |
| sdfull-accepted-http | 2 | 1 | 0 | 168.09 |
| sdfull-keep-green | 2 | 0 | 0 | 62.44 |
| sdfull-r1-atomic-green | 2 | 0 | 1 | 47.62 |
| sdfull-reservation-green | 1 | 0 | 0 | 12.38 |

Final narrowed commands / mapping:

- Domain: `packages/domain/tests/test_smart_defaults_candidate.py` (11 cases).
- Prompts: `packages/prompts/tests/test_completion_candidate.py packages/prompts/tests/test_completion.py` (12); then only the two added `test_missing_mandatory_choice_cannot_be_discharged_by_no` cases (2).
- API: `apps/api/tests/test_completion_migration.py` (5 earlier migration/activation/storage cases); added `::test_completion_routes_absent_by_default` (1).
- API: `apps/api/tests/test_prompt_completion.py::test_complete_unknown_refine_restart_replay_and_latest` (1 final persisted journey; rerun justified by schema-aware target validation change).
- API: `test_completion_scope_idempotency_and_tamper` passed in accepted-http receipt (2 passing cases there include earlier main journey). Unchanged scope/idempotency boundary was not rerun.
- API: `test_completion_rejects_pending_keep_atomically test_completion_conflicting_material_is_not_defaulted` (2, after correcting only the blocking/nonblocking unbound distinction).
- API: `apps/api/tests/test_completion_candidate_http.py apps/api/tests/test_prompt_completion.py::test_completion_validation_failure_rolls_back_append apps/api/tests/test_prompt_completion_postgres.py` (2 PASS, 1 SKIP).
- API: `test_completion_write_reservation_never_rewinds_cached_revision` (1).
- Ruff check/format: all 18 changed Python files PASS. `git diff --check` PASS.

PostgreSQL: NOT VERIFIED locally. The guarded lifecycle/Alembic check is SKIP because
no TEST_POSTGRES_URL was supplied; independent disposable-target gate is retained.
Warnings: existing Starlette/anyio deprecation; one JUnit record_property/xunit2 warning
(properties are nevertheless present in the XML). No warning represented a skipped assertion.

## Failed development commands / corrections

No unchanged failing command was blindly repeated. Failures were investigated first:

- Early unit fixture expected `.value` from absent `metal.finish`; corrected only the fixture assertion.
- Early HTTP harness: missing Message helper, then whole-conversation equality after intentionally adding a NO Message; corrected harness / compare canonical revision+state.
- Superseded-value test initially tried to discard independent yellow color with the gold material; corrected expectation to existing independent-property semantics, not Parser behavior.
- Activation validation initially placed in the wrong settings dataclass; targeted construction exposed and corrected it before publication.
- SQLite writer-reservation adversarial fixture initially passed UUID text to a UUID repository API; corrected the fixture. The product change reserves column=self and refreshes without writing cached values.
- One development command was interrupted (exit130, zero completed cases) upon discovering that fixture edit had not matched formatted code. No full suite was launched.
- accepted-http: 2 PASS / 1 FAIL, 168.10s. Explicit KEEP REJECT left native NONBLOCKING unaccepted evidence; completion incorrectly rejected it as conflict. Corrected new IFP6 policy projection to retain nonblocking unresolved evidence while still refusing blocking unbound/material competing evidence. Narrow keep-green 2 PASS.
- Reviewer R1: actual persisted candidate/source-verified IFP parity failed in 28.47s. Added propagation of verified source facts/pending descriptions, parity + restart now PASS.
- Reviewer R2: exact nested Unknown `.value` wrongly accepted; RED receipt has 2 failures (one actual acceptance defect; one negative-control error-message mismatch). Schema-aware State-path membership now rejects nested wrapper fields. 11 PASS.

## Actual full Input → Output

Input: `A yellow gold engagement ring with an oval diamond center stone.`
Persisted initial command → actual contextual UNKNOWN → SKIP → YES/EDITING →
`Use a prong setting.` correction → NO/FINAL. Test-only approved contextual
policy supplies dimensions8×6×4 as Assumed, never user-confirmed canonical data.
Repeated command returns identical artifact; restart returns identical current artifact.
`Use platinum. Center stone 9 x 7 x 4 mm.` → old completion invalidated409, stale
command409, new NO produces new IFP6; original replay is_current=false.

Exact active prompt text captured by final HTTP test (synthetic data only):

### initial_ifp6_prompt

```text
JEWELAI INTERNAL FINAL PROMPT 6.0.0
CURRENT EFFECTIVE DESIGN
jewelry_type: "ring" [explicit; value]
metal.material: "gold" [explicit; value]
metal.color: "yellow" [explicit; value]
center_stone.material: "diamond" [explicit; value]
center_stone.shape: "oval" [explicit; value]
center_stone.dimensions: {"depth": {"unit": "mm", "value": 4.0}, "length": {"unit": "mm", "value": 8.0}, "width": {"unit": "mm", "value": 6.0}} [assumed; value]
center_stone.setting: "prong_setting" [explicit; value]
ACTIVE CONSTRAINTS — MUST PRESERVE
Preserve this authoritative design value.
Preserve this authoritative design value.
Preserve this authoritative design value.
Preserve this authoritative design value.
Preserve this authoritative design value.
Preserve this authoritative design value.
LEFT UNSPECIFIED — DO NOT INVENT
```

### corrected_ifp6_prompt

```text
JEWELAI INTERNAL FINAL PROMPT 6.0.0
CURRENT EFFECTIVE DESIGN
jewelry_type: "ring" [explicit; value]
metal.material: "platinum" [explicit; value]
metal.color: "yellow" [explicit; value]
center_stone.material: "diamond" [explicit; value]
center_stone.shape: "oval" [explicit; value]
center_stone.dimensions: {"depth": {"unit": "mm", "value": 4.0}, "length": {"unit": "mm", "value": 9.0}, "width": {"unit": "mm", "value": 7.0}} [explicit; value]
center_stone.setting: "prong_setting" [explicit; value]
ACTIVE CONSTRAINTS — MUST PRESERVE
Preserve this authoritative design value.
Preserve this authoritative design value.
Preserve this authoritative design value.
Preserve this authoritative design value.
Preserve this authoritative design value.
Preserve this authoritative design value.
Preserve this authoritative design value.
LEFT UNSPECIFIED — DO NOT INVENT
```

### initial_policy_sha256

```text
1b55f92826eede7256710f5dc205f520bc379c95bfca352db84ca9345ad85d38
```

## Criterion evidence / remaining gates

VERIFIED PASS (developer execution): latest-state defaults, explicit provenance,
canonical nonmutation, UNKNOWN/SKIP completion, repeated refinement, durable YES/NO,
currentness/invalidation, idempotency, CAS, restart, pending KEEP refusal and explicit
REJECT continuation, LOCK unit guard, scoped authorization, tamper detection,
precommit failure rollback, default-off routes and approved registry/hash startup guards.
IFP4/5 validators and legacy API response contracts remain unchanged; reviewer R1
parity regression directly compares the entire existing IFP4 assembly.

NOT TESTED: real PostgreSQL execution/concurrency/append-only trigger; live preprod;
frontend integration; provider/downstream6 consumption; every existing historical variant;
full EN/RU HTTP completion matrix. RU completion question/choice handling exists but
full RU persisted flow is not claimed from the EN smoke.

Approval gates: independent functional/contract review, professional policy review
and exact artifact pinning, authorized shared migration/rollout, separate UI integration.
Checked-in policy is PROPOSED and cannot activate. Quantitative rule is TEST ONLY.
No independent acceptance or production readiness claimed.
