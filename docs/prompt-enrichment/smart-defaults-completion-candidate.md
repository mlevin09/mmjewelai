# Smart Defaults and completion — unregistered backend candidate

Historical PR155 candidate scope. The separate full opt-in runtime implementation
is documented in [completion-api-v1.md](completion-api-v1.md) and ADR0040; this
document does not activate or redefine the original candidate.

Status: **proposal / development only**. No route, persistence, migration, policy
catalog, renderer activation or readiness override. This is not a completed live
completion workflow. Owner approval of the product goal is not approval of these
new evidence/read/storage contracts. ADR0037/0038 and historical IFPs stay frozen.

## Phase A: findings and selected architecture

Baseline `c7c81ebabbf2a257afb13599a9d90940e20b40a2` contains PR153's Web
completion UI. The UI's finish action is not a durable backend completion intent.
PR154 head `810df9a37e222a284a3c13dd95bdf33a175ca9e9` contains only a pure
candidate selector and tests plus a one-time workflow. Its Domain run42193728642
ran588 tests then failed Ruff F401 (unused Field); Runtime42193728684 and one-time
42193722153 failed; Web42193728674 passed. No acceptance or merge inferred.

This branch reuses the selector/tests, removes the unused import and repairs
per-jewelry-type duplicate-target selection and validation-before-protection.
It does NOT copy PR154's workflow or introduce factual default values.

Current chain: authorized persisted Message -> Parser1.2 -> ParserProposal /
Dictionary / Library -> revision/CAS -> scoped native/F05 read -> Matrix/rules /
frontier/protection -> Description3/IFP4 (internal opt-in Description4/IFP5).
`continuation_preview.read_preview` rejects final output at409 if BLOCKED.
IFP4/5 validators themselves prohibit READY with blocking native causes or pending
preservation requests. GET must remain read-only and cannot imply completion.

| Blocker | Candidate behavior | Future decision |
| --- | --- | --- |
| Missing optional/explicitly unknown information | Existing READY_WITH_UNRESOLVED can return unchanged after NO | Approved policy may propose an assumption; never convert Unknown to user fact |
| Missing value with applicable type-scoped rule | Typed Assumed overlay + review compilation only | Approve exact policy/value/provenance and new IFP family |
| Native blocking information gap | Keep old IFP blocked, CONTRACT_APPROVAL_REQUIRED | Exact cause/criticality/UNKNOWN/SKIP discharge policy required |
| Conflicting alternatives/unbound evidence | Never discharged by NO/default | Existing explicit resolution required |
| Pending KEEP release | PROTECTION_BLOCKED, no defaults or final output | Existing separate explicit consent only |
| LOCK/confirmed/not-applicable/current known value | Never replace | No new override semantics |
| Scope/hash/stale full-frame mismatch | ValueError before result | Adapter maps bounded409/422 using existing conventions |

Recommend a separately versioned **effective-state overlay**, not a silent
canonical EDIT. It reuses canonical Assumed/RuleSource for each overlay leaf,
validates the entire retained schema and never commits a DesignRevision. AI_DEFAULT
is the proposal label; canonical origin remains `assumed`, not explicit or derived.
Policy rules are supplied and hashed, not chosen by an LLM. No numeric defaults
are shipped. Test policies are not professional approvals. Active/unbound accepted
constraints conservatively withhold defaults. No repeated groups are created.

The existing CompiledPrompt is used ONLY to inspect/render an overlay. It is NOT
the Internal Final Prompt. `review_compilation` cannot authorize finalization.
An unchanged existing IFP4/5 is returned only after exact NO, with no applied
defaults and existing readiness permitting it. Otherwise final_prompt=null and
CONTRACT_APPROVAL_REQUIRED. This intentionally exposes, rather than conceals,
the requested end-to-end finalization gap.

## Proposed interface for UI integration (not a public endpoint)

Python-only `prepare_completion_candidate(snapshot,intent,policy,dictionary=...,templates=...,output_version="4.0.0")`.
The snapshot must be freshly source-verified under the existing scoped repository
transaction; it is NOT a browser-submitted DTO. No module imports/registers this
candidate in create_app. Use of internal opt-in5 does not add public output5.

Proposed command body (placeholder values, not executable credentials):

```json
{"schema_version":"completion-intent-candidate/1.0.0",
 "request_id":"<UUID>","message_id":"<persisted human YES/NO Message UUID>",
 "scope":{"organization_id":"<UUID>","session_id":"<UUID>","design_id":"<UUID>"},
 "expected_frame":"<complete existing ContinuationFrame object>",
 "anything_else":"NO","recorded_at":"<server UTC time>","content_hash":"<server hash>"}
```

The actual model requires the full typed frame, not the illustrative string above.
Hash domain `jewelai.CompletionIntentCandidate/1.0.0` includes all other fields.
The future HTTP adapter must construct timestamps/hashes server-side, verify
Message/actor ownership and explicit YES/NO, authorize membership, lock the exact
current frame, persist idempotency+intent+result atomically and store immutable
output lineage. A caller-supplied hash is integrity evidence, not authentication.

Proposed response is CompletionReviewCandidate (candidate1.0.0):

- EDITING: YES, no final prompt; keep clarification/correction flow available.
- FINAL_AVAILABLE: NO + current existing ready IFP4/5, no overlay required.
- PROTECTION_BLOCKED: pending explicit preservation consent, no defaults.
- CONTRACT_APPROVAL_REQUIRED: defaults require an overlay-aware IFP contract,
  or current native readiness remains BLOCKED. No false READY artifact.
- defaults: target/value, AI_DEFAULT label, rule ID/version/rationale, exact
  basis revision ID/hash and candidate hash. Policy hash covers full registry.
- review_compilation: typed non-authoritative overlay compilation, never handoff.
- remaining_blocker_targets: current blocking details; empty does NOT imply ready
  (rule-level blockers and pending protection can be untargeted).

Same inputs return identical result/hash. This is pure recomputation, NOT durable
request-ID replay protection. Any revision/cycle/plan/history hash change rejects
the old completion frame. A new completion must be issued after correction;
older serialized results remain bound to their original frame and are not current.
No fixed clarification-round limit exists in this candidate.

## Exact activation gates / remaining implementation

1. Approve policy registry release ID, reviewed per-jewelry rules/values and allowed
   applicability contexts; numerical recommendations are not automatic defaults.
2. Approve overlay vs canonical Assumed EDIT. Current recommendation is overlay;
   authoritative Product State is unchanged until this is explicitly decided.
3. Approve a new completion-aware IFP/read family, with exact coverage and cause
   discharge proofs. Do NOT change IFP4/5 readiness validators or historical hashes.
4. Approve durable completion schema/Message semantics, transaction/CAS/idempotency,
   output invalidation, retention and any migration before persistence implementation.
5. Approve opt-in endpoint/version, auth, server-authored evidence and runtime flag.
   No automatic activation from a feature flag/approval boolean is implemented.

Only then implement real UNKNOWN/SKIP/all-optional and NO finalization, persistence
and UI integration. No policy approval can override pending KEEP or active LOCK.
No frontend files changed. No live/API/DB writes, deployment or provider calls.

## Functional Definition of Done and evidence

The candidate's selectors/overlay/full-frame gates can be tested locally. The full
product DoD is **NOT PASS**: durable YES/NO, replay ledger, optional/required native
UNKNOWN/SKIP discharge, overlay-aware final IFP and activation remain Owner-gated.
Unit typed frames are synthetic; the scoped API HTTP/restart test uses persisted
SQLite and existing TEST-ONLY Knowledge/authentication, not a live deployment.
Real partner UI integration and production default values are NOT TESTED.
Commands and actual results belong in the Draft PR; no Full Regression required
or executed merely to approve this isolated proposal.

### Acceptance coverage (development evidence)

| Requested case | Actual evidence / status |
| --- | --- |
| Current ready design + NO, no defaults | VERIFIED PASS: typed4/5 tests, unchanged serialized IFP bytes; persisted F HTTP example |
| Partial design + defaults | VERIFIED PASS for typed Assumed overlay; authoritative finalization NOT TESTED / approval required |
| All optional UNKNOWN/SKIP | NOT TESTED as a material-answer completion journey; discharge contract pending |
| Several clarification rounds + NO | NOT TESTED as clarification answers; three persisted correction rounds verified separately |
| YES -> more information -> NO | YES gating unit PASS; corrected snapshots and NO PASS; no durable YES event |
| User replaces previous assumption | Overlay recomputation test PASS (matte replaces polished); canonical assumed EDIT not implemented |
| Superseded values absent | Current structured facts platinum/matte and no old polished in final text PASS; HTTP platinum after gold/platinum sequence PASS |
| LOCK/KEEP | Existing explicit/locked state selector controls and HTTP KEEP PASS; no authority transition introduced |
| Pending KEEP consent | VERIFIED PASS: PROTECTION_BLOCKED, no defaults/final artifact |
| CAS/scope | Exact full-frame/scope mismatch rejected; HTTP current/stale and restart PASS; DB transaction CAS not implemented for completion |
| Determinism/provenance/hashes | VERIFIED PASS: intent/default/result roundtrip and deterministic recomputation |
| Replay/idempotency | Pure deterministic replay PASS; durable request-ID conflict/dedup NOT IMPLEMENTED |
| Historical compatibility | Existing IFP4/5 byte-equality tests PASS; old models/readers unchanged; historical completion records do not exist |
| Reedit completed design | Changed current revision requires new intent; stale original rejected PASS; stored output-current lookup not implemented |
| Different jewelry types | Ring vs earrings rule scoping PASS with TEST-ONLY values; no approved production registry |

Initial new test fixture incorrectly used legacy enrichment1.2 with a current F05
snapshot; corrected to the existing F06 fixture's current1.3 enrich_prompt helper.
No frozen validator was relaxed. Invalid nested target under a confirmed ancestor
was previously skipped; target validation now precedes protection filtering.
Pending consent test exposed the existing requirement for sourced pending-request
rendering; candidate now validates the snapshot and returns PROTECTION_BLOCKED
without attempting incomplete final assembly. Failed test receipts were retained
locally; they are test/implementation development findings, not live regressions.
