# PR156 — Targeted acceptance corrections: Owner Input → Output

Starting HEAD: `76121f0fb98a8fbc1cca1c59a2f43896438d3d8c`.
Final HEAD and automatic CI are recorded in the PR summary (not self-embedded in this commit).
Same development branch/PR; PR155 stays frozen. No merge/deploy/shared migration,
provider request, professional policy activation or frontend edit.

## Findings and observable outcomes

| Requirement | Before | After / developer evidence |
|---|---|---|
| R1 known KEEP value | oval also in LEFT UNSPECIFIED | VERIFIED PASS: actual F05 admission → Emerald-cut request → KEEP_RELEASE REJECT → NO. oval active, KEEP retained, no shape omission; unbound interpretation retained in base evidence. |
| R2 scoped preservation | targetless generic instructions | VERIFIED PASS: field LOCK names metal.color/white; field KEEP names center_stone.shape/oval; actual coalesced center-stone KEEP includes current owned values and original instruction. Structured constraint identities remain unchanged. |
| R3 durable source | rehashed YES returned NO/FINAL; assistant actor accepted; moved source returned404 | VERIFIED PASS: GET and replay return500 invalid_completion_history for changed choice, actor or session scope, even with otherwise consistent record hashes. |
| Existing positive completion | previously independently PASS | VERIFIED PASS again: actual UNKNOWN/SKIP → YES → refinement → NO/IFP6 → restart/replay → platinum9×7×4 correction → invalidation → recompletion. |
| Policy ownership | unmapped_fixture_data | VERIFIED PASS local mapping controls: complete Domain/Prompts directories and complete API completion namespace. Unowned resources still fail; shared app/model Full flag stays true. Exact final selection receipt is in PR. |
| PostgreSQL completion proofs | one sequential wrapper, no execution | NOT TESTED / 9 SKIP locally: no Docker/Podman/psql/postgres, no TEST_POSTGRES_URL and no legitimate runtime job. Guard unchanged and not simulated. |
| Frozen contracts | IFP4/5 and guard frozen | VERIFIED PASS diff inspection: unchanged IFP4/5 renderers/validators, disposable_postgres.py, migration and professional policy file. |
| Exact-SHA Full qualification | required, not authorized | NOT TESTED / BLOCKED pending explicit Owner authorization on final SHA. No manual Full or duplicate workflow launched. |

## Actual R1 authoritative text

```text
JEWELAI INTERNAL FINAL PROMPT 6.0.0
CURRENT EFFECTIVE DESIGN
jewelry_type: "ring" [explicit; value]
metal.material: "gold" [explicit; value]
metal.color: "white" [explicit; value]
center_stone.material: "diamond" [explicit; value]
center_stone.shape: "oval" [explicit; value]
center_stone.dimensions: {"depth": {"unit": "mm", "value": 4.0}, "length": {"unit": "mm", "value": 8.0}, "width": {"unit": "mm", "value": 6.0}} [explicit; value]
center_stone.setting: "prong_setting" [explicit; value]
ACTIVE CONSTRAINTS — MUST PRESERVE
requirement center_stone.dimensions: {"depth": {"unit": "mm", "value": 4.0}, "length": {"unit": "mm", "value": 8.0}, "width": {"unit": "mm", "value": 6.0}} — Preserve this authoritative design value.
requirement center_stone.material: "diamond" — Preserve this authoritative design value.
requirement center_stone.setting: "prong_setting" — Preserve this authoritative design value.
requirement center_stone.shape: "oval" — Preserve this authoritative design value.
preservation component.center_stone: {"center_stone.dimensions": {"depth": {"unit": "mm", "value": 4.0}, "length": {"unit": "mm", "value": 8.0}, "width": {"unit": "mm", "value": 6.0}}, "center_stone.material": "diamond", "center_stone.setting": "prong_setting", "center_stone.shape": "oval"} — Keep the current center stone unchanged.
requirement jewelry_type: "ring" — Preserve this authoritative design value.
requirement metal.color: "white" — Preserve this authoritative design value.
requirement metal.material: "gold" — Preserve this authoritative design value.
LEFT UNSPECIFIED — DO NOT INVENT
```

The rejected interpretation remains in base_prompt.unresolved_details with its
original source references. It is not a missing accepted value. Genuinely missing
parameters and blocking/conflicting evidence keep the existing approved rules.

## Actual latest-state completion outputs

initial_ifp6_prompt:

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
requirement center_stone.material: "diamond" — Preserve this authoritative design value.
requirement center_stone.setting: "prong_setting" — Preserve this authoritative design value.
requirement center_stone.shape: "oval" — Preserve this authoritative design value.
requirement jewelry_type: "ring" — Preserve this authoritative design value.
requirement metal.color: "yellow" — Preserve this authoritative design value.
requirement metal.material: "gold" — Preserve this authoritative design value.
LEFT UNSPECIFIED — DO NOT INVENT
```

corrected_ifp6_prompt:

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
requirement center_stone.dimensions: {"depth": {"unit": "mm", "value": 4.0}, "length": {"unit": "mm", "value": 9.0}, "width": {"unit": "mm", "value": 7.0}} — Preserve this authoritative design value.
requirement center_stone.material: "diamond" — Preserve this authoritative design value.
requirement center_stone.setting: "prong_setting" — Preserve this authoritative design value.
requirement center_stone.shape: "oval" — Preserve this authoritative design value.
requirement jewelry_type: "ring" — Preserve this authoritative design value.
requirement metal.color: "yellow" — Preserve this authoritative design value.
requirement metal.material: "platinum" — Preserve this authoritative design value.
LEFT UNSPECIFIED — DO NOT INVENT
```

All content above is synthetic test data. Quantitative8×6×4 remains TEST ONLY.

## Source and scope

Production changes are confined to `packages/prompts/src/jewelai_prompts/completion.py`
(known-vs-unaccepted classification and deterministic scoped rendering) and
`apps/api/src/jewelai_api/completion.py` (shared write/read/replay choice/actor/session
validation, typed invalid-history for missing scoped durable sources). Hash, frame,
authority, principal and actual revision/cycle verification remain enforced.

Existing completion tests moved intact into `apps/api/tests/completion/` to establish
a complete owning directory under the existing fixture_scopes policy. New actual-file
loader/contextual HTTP tests exercise `data/completion/proposed-1.0.0.json`; only a
temporary explicitly TEST-ONLY APPROVED copy is used. The shipped file stays PROPOSED.
No test inventory is dropped to evade selection. New mapping is proposed for review,
not an override; unrelated unowned data and shared Full gating remain fail-closed.

## PostgreSQL proof inventory / external execution limitation

Existing independently verified disposable fixture remains the only DDL entry. Added:
1. Existing full UNKNOWN/SKIP/YES/NO/edit/restart HTTP lifecycle.
2. Concurrent identical requests: one row/artifact and one replay.
3. Distinct YES/NO: unique1/2 sequence and deterministic latest/replay currentness.
4. Both real row-lock race orders: edit first rejects stale completion; completion
   first is valid at its commit and becomes non-current after edit.
5. Actual UPDATE and DELETE trigger refusal, original artifact unchanged.
6. Injected post-flush validation failure rolls back.
7. No-DML GET/restart, tenant denial, idempotency and source corruption refusal.

All nine parametrized PostgreSQL cases are SKIP locally. They are assertions awaiting
authorized execution, not evidence of actual PostgreSQL success. ContextVar propagation
used only for test scheduling was separately verified through installed FastAPI sync
TestClient; PostgreSQL locks are never mocked. No shared service was accessed.

## Test execution ledger

All commands use explicit file/node IDs below, native package pyproject.toml and -q.
No full API execution, Full Regression, manual dispatch or unchanged failure retry.

| Local command receipt | Cases | Fail | Skip | Seconds |
|---|---:|---:|---:|---:|
| sdfix-r2-red | 2 | 2 | 0 | 2.06 |
| sdfix-r13-red | 4 | 4 | 0 | 66.59 |
| sdfix-prompts-green | 8 | 0 | 0 | 2.18 |
| sdfix-r13-green | 4 | 1 | 0 | 63.12 |
| sdfix-r1-green | 1 | 0 | 0 | 40.69 |
| sdfix-policy-green | 8 | 0 | 0 | 15.12 |
| sdfix-ci-ownership | 4 | 0 | 0 | 0.93 |
| sdfix-lifecycle-green | 1 | 0 | 0 | 47.09 |
| sdfix-postgres | 9 | 0 | 9 | 0.44 |

Commands/scopes:

- R2 RED: test_completion.py::{test_ifp6_does_not_override_locked_user_value,test_ifp6_field_keep_names_current_target_and_value}.
- R1/R3 RED: original API test_prompt_completion.py::{test_completion_rejects_pending_keep_atomically,test_completion_rejects_rehashed_inconsistent_source} (choice/actor/scope).
- Prompt GREEN: packages/prompts/tests/test_completion.py (8 cases).
- R1/R3 first GREEN attempt:3 PASS; R1 product omission assertion passed, but test split incorrectly required a trailing newline after an empty unspecified section. Fixed only test partition; reran only R1 (1 PASS).
- Policy GREEN: apps/api/tests/completion/{test_policy_registry.py,test_completion_migration.py} (8 cases).
- CI mapping: tools/ci/tests/test_completion_policy_scope.py and existing test_fixture_scope_policy.py::test_invalid_or_full_api_mapping_cannot_clear_gate (4 cases).
- Main journey: apps/api/tests/completion/test_prompt_completion.py::test_complete_unknown_refine_restart_replay_and_latest (1 PASS).
- PostgreSQL: apps/api/tests/completion/test_prompt_completion_postgres.py (9 SKIP).
- Ruff check initially reported formatting/import issues in new tests; formatter/import fix applied, then checks PASS. git diff --check PASS.
- Warnings disclosed: existing anyio deprecation, JUnit record_property/xunit2, tooling pytest unknown asyncio_mode. No failed assertion was waived.

## Remaining gates / next action

Independent review of corrections and ownership; actual disposable PostgreSQL cases;
one separately authorized exact-final-SHA Full Regression (existing policy/budget),
followed by established lightweight qualification recheck. Automatic PR checks do not
substitute for Full. No workflow policy or qualification requirement was relaxed.
Professional policy review/pin, authorized shared migration/opt-in rollout and Studio
integration remain separate. Development does not self-certify independent acceptance.
