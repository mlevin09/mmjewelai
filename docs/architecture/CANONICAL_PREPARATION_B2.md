# Canonical preparation B2 — bounded, not deployed

B2 follows the Owner-approved single-path R1 design and merged B1 (PR #129). It does not complete
the worker/Web cutover. No professional release is activated or qualified by synthetic tests.

## Current source and versioned history

Current enrichment emits `StructuredPromptEnrichmentResult` **1.3.0**: existing matrix/decisions,
release lineage, typed references, structured revision entries/locks/disclosures and template pin.
It uses `project_revision`, never the legacy text compiler. B2 initially emitted B1's **2.0.0**
final-output/handoff contracts. The bounded [IFP capacity successor](../adr/0034-versioned-ifp-capacity-v2-1.md)
selects **2.1.0** for new assembly while preserving exact 2.0 readers and preparation replay.
Existing enrichment **1.2.0**, IFP **1.1.0**, handoff **1.0.0** and
prompt-revision bytes retain original readers, JSON schemas and hashes. Historical nested results
are decoded by their original version; they are not rewritten into 1.3. Existing policy, parser,
authority precedence and professional source data are unchanged.

## Authoritative HTTP boundary

`POST /sessions/{session_id}/generation-preparations` requires normal bearer membership,
`X-Organization-ID`, UUID `Idempotency-Key`, and strict request schema **1.0.0** with:

- `expected_revision_id`
- `expected_enrichment_cycle_id`, `expected_enrichment_cycle_number`
- `expected_enrichment_result_hash`, `expected_handoff_hash`
- `expected_clarification_plan_hash`, `expected_decision_frontier_hash`

The controlled enrichment state response exposes these expectations and `can_prepare`. These are
optimistic concurrency tokens, not client authority. No caller supplies source, gate, rendering,
release-verification flags or provenance. No provider is called. Creation is unavailable when the
existing controlled enrichment runtime is not configured.

One SQLAlchemy transaction locks the organization (same order as membership changes), rechecks
membership, locks the scoped session, resolves replay, and reloads revision/cycle/plan/decision
frontier. All repository reads reuse this exact locked Session, not another transaction. ACTIVE
runtime/report bytes are verified against the session pin by the existing artifact loader. The
existing deterministic final-output builder and B1 renderer enforce effective readiness and coverage.

The server compares every expected binding, constructs immutable preparation bytes, validates real
revision/cycle/plan/frontier relationships, and commits artifact plus frozen response atomically.
Failures leave neither row. An identical replay rechecks authorization and retained integrity and
returns the frozen original response (**200**); new creation returns **201**. A changed request with
the same scoped key yields **409 idempotency_conflict**. Historical replay is readback only, NEVER
authorization to dispatch a new generation against obsolete state.

`GET /sessions/{session_id}/generation-preparations/{preparation_id}` returns only the scoped
summary: IDs, versions, hashes, readiness/unresolved summary and creation time. Full source,
rendering and professional provenance stay server-side. Missing/foreign resources remain scoped
404s. Conflict, invalid history, unavailable release/storage, unsupported semantics and capacity
overflow fail closed with bounded codes, never raw validation/source payloads.

## Additive storage, not execution cutover

Migration **0016_generation_preparations**, after **0015_reference_verification**, adds only:

- Scope-addressable unique keys on existing project/session/revision/cycle identities.
- `generation_preparation`: exact artifact/source bytes, mirrored scope and hashes, composite FKs.
- `generation_command`: scoped command/key, request hash, exact success response and its hash.
- PostgreSQL append-only UPDATE/DELETE rejection triggers for those two new tables.

There is no historical data rewrite/backfill. Migration 0016 **always refuses online downgrade**,
whether retained tables are empty or populated. It raises a deterministic operational error before
any migration database operation, lock or DDL. The earlier child-table locking protocol prevented
data loss but could deadlock with command lookups or FK parent locks; it is superseded by this
fail-closed policy (B2-R1a). Safe operational rollback must retain schema 0016 and reader-compatible
application code. Any schema rollback requires a separately planned maintenance operation, not
table deletion, cleanup of retained history or a production escape hatch.
The existing run/iteration tables
are untouched: nullable preparation references, discriminators/XOR and their complete reader/worker
updates are deferred together to B3 because **B2 creates no preparation-backed runs**. There is no
partially enabled mixed-input execution contract.

0016 must run only on independently verified disposable PostgreSQL during this draft. New tests
verify the actual fresh CI Postgres 16 container, mapped localhost port and cluster identity BEFORE
creating an owned random test schema. They never accept an arbitrary database URL merely because
it contains `test`. Locally these critical tests explicitly SKIP if no verified container exists;
SKIP is not PASS. Existing historical SQLite migration coverage ends at 0015. Issue #114's older
arbitrary-URL fixtures are not broadened or fixed opportunistically here.

## Required race interpretation

T1 captures expected revision R/cycle C3 before acquiring the preparation lock. T2 commits a
constraint-only no-halo correction R/C4. T1 acquires the lock, re-reads C4 and rejects C3 with 409;
no stale artifact/command is retained. An answer-frontier change also invalidates stale tokens
without requiring a revision change. If T1 already holds the session lock, T2 must wait: the tests
do not claim two concurrent writers can bypass that lock. Revocation between HTTP authorization
and the transaction is independently rechecked inside the transaction.

## Complete legacy NEW-write inventory / B3 dependencies

All routes below remain unchanged and explicitly **not cut over** in B2. Retiring them independently
would break the existing Web/worker or decide image-edit policy outside this review.

| Existing route/call path | B2 disposition | Required coordinated B3 work |
| --- | --- | --- |
| `POST /sessions/{id}/prompt-revisions` → `RuntimeService.create_prompt_revision` → legacy compiler | Retained | Retire standalone compilation with Web canonical preparation integration |
| `POST /sessions/{id}/generation-runs` → single-run/outbox | Retained | Retire NEW legacy input, change worker input/readers atomically |
| `POST /sessions/{id}/visualization-iterations` → grouped runs/outboxes | Retained | Reject old input only when canonical fan-out/worker/UI can consume preparation |
| `POST /sessions/{id}/text-intake` → Google understanding → parser proposal/revision | Retained | Replace caller with existing message/internal enrichment flow during Web cutover |
| `POST /sessions/{id}/iterative-edits` and `.../{edit_id}/messages` → prompt revision and edit iteration | Retained | Owner image-reference/cutover decision plus compatible canonical image-conditioned worker |
| `POST /sessions/{id}/generation-runs/{run_id}/retry` | Historical exact-input semantics retained | Preserve original input, parent/recovery lineage and historical readers |
| All prompt/run/iteration/selection/Asset historical GET and completion/recovery/reconciliation readers | Preserved | Continue compatibility when B3 adds the new input discriminator |

Existing API/worker/pipeline regression suites cover these paths. No preparation ID is accepted by
old iteration/run request schemas; B2 adds no fallback, dispatch/outbox/publisher call, mode switch,
Web code or worker/provider modification. Draft/non-deployed B2 does **not** establish a second
active generation product and does **not** claim the HTTP→worker no-halo P1 is fixed.

## Remaining independent review / Owner decisions

Review transaction scope, nested history, immutable retention and PostgreSQL proof before merge.
B3 must coordinate the only NEW-generation cutover and the still outstanding image-edit product
policy. B4 must prove persisted HTTP→worker semantic delivery. Capacity limits remain B1's
provisional bounds; real Knowledge v1.1 release qualification/activation is not evaluated here.

## Independent-review remediation (B2-R1–R4; draft only)

Preparation/GET use PostgreSQL organization `FOR NO KEY UPDATE` (SQLAlchemy
`with_for_update(key_share=True)`). This still conflicts with membership revocation's `FOR UPDATE`,
but is compatible with FK `KEY SHARE` from session-first correction/answer writers. Session locking,
transaction-time membership checks and exact revision/cycle/frontier conflicts remain unchanged;
there is no automatic retry against changed state.

Retained handoff, embedded IFP and gate must match all four Knowledge release components of the
verified historical cycle/persisted immutable pin. Template/enrichment versions bind to that cycle;
dictionary/question/rules versions bind to its historical plan. Historical read/replay does not
require equality with the latest mutable revision, cycle or decision frontier.

For enrichment 1.2 only, an isolated read-only verifier reuses the frozen renderer plus canonical
revision projection to compare the complete original compiled source, including exact text and
template metadata. Recomputing inner/outer hashes cannot authorize a different rendering. It never
calls `compile_prompt`, rewrites bytes or produces a current generation input. Current structured
1.3 bypasses this historical branch and remains compiler-free. Frozen compiler/template/catalog
artifacts and schemas remain unchanged.

Barrier/event-controlled disposable PostgreSQL regressions exercise early command lookup and
FK-parent overlap with a refused downgrade, correction and answer overlap with creation/GET, and
actual revocation lock contention. Downgrade tests require normal concurrent POST success, retained
schema/rows/hashes, and zero driver SQLSTATE 40P01 or server deadlock messages; arbitrary HTTP 503 is
not accepted. Empty and populated downgrade attempts both refuse without database operations.
Test cleanup uses only the verified owned-schema teardown, never a downgrade workaround. Local
PostgreSQL skips are not evidence of success; final exact-head CI must execute every critical case.
No persistent migration, B3 dispatch, Web/provider change, merge, release activation or deployment
is authorized by this remediation.
