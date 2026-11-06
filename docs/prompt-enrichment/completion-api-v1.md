# Backend completion v1 / IFP6 — UI integration handoff

Implementation: opt-in, unmerged Draft. Supersedes the functional limitations of
PR155, not its frozen evidence. Existing final-output4/IFP4 and internal IFP5
semantics remain unchanged. No frontend integration or live acceptance claimed.

## Enablement (separate reviewed rollout only)

Apply reviewed migration0019 on an authorized environment, qualify a reviewed
CompletionRegistry1.0.0 and pin its exact domain-separated SHA256. Set:

- PROMPT_COMPLETION_ENABLED=true (default false)
- PROMPT_COMPLETION_POLICY_PATH=<immutable approved registry file>
- PROMPT_COMPLETION_POLICY_SHA256=<registry.sha256>

Wrong/missing hash or PROPOSED registry fails startup. The new routes do not exist
with default settings. Checked-in data/completion/proposed-1.0.0.json is an initial
reviewable PROPOSAL (ring/gold vs earrings/platinum context examples); do not rename
it APPROVED without domain/Owner review. No numeric professional policy is supplied.
The implementation and tests work with an injected explicitly reviewed TEST-ONLY
registry, not an approval-bypass request header or client-selected policy.

## Existing workflow -> completion

Use existing session, persisted Message, parsing, clarification and correction
APIs. No round counter/cap is introduced. With an initialized conversation, GET:

`/v1/sessions/{session_id}/prompt-enrichment/completions/current`

Authenticated Bearer and X-Organization-ID remain mandatory. Before any completion
this returns200 CompletionContext:

```json
{"schema_version":"completion-context/1.0.0","status":"AWAITING_COMPLETION",
 "expected_frame":{"revision_id":"...","revision_sha256":"...","enrichment_cycle_id":"...",
 "enrichment_cycle_number":1,"enrichment_result_hash":"...","plan_id":"...",
 "plan_hash":"...","history_root_sha256":"..."},
 "question":{"question_id":"ANYTHING_ELSE/1.0.0",
 "text":"Anything else you would like to add?","choices":["YES","NO"]}}
```

RU sessions receive localized question text. This is a completion question, not a
native clarification answer or a policy acceptance/release decision.

Persist the explicit user choice through POST /sessions/{id}/messages using content
YES or NO (Да/Нет also accepted). Then send the typed command:

```js
const request = {
  schema_version: "1.0.0",
  request_id: crypto.randomUUID(), // retain this entire body for transport retries
  message_id: storedMessage.message_id,
  expected_frame: conversation.state.current_frame, // full server-provided object
  anything_else: "NO" // or YES
};
// POST /v1/sessions/{id}/prompt-enrichment/completions
```

Do not recalculate frame hashes. Empty text, inactivity and GET never record NO.
Only a scoped stored user Message plus explicit command can finalize. Message
creation and completion are separate existing boundaries; a rejected command may
leave its user Message visible, but no partial completion/revision/cycle commits.

YES response: status EDITING, final_prompt=null; return to normal refinement.
NO response: status FINAL, is_current=true, replayed=false, completion_id,
expected_frame, record content_hash, completion question, and final_prompt6.0.0.
Display final_prompt.prompt_text and effective_parameters. Read each parameter's
source from parameter_sources; assumptions carry AI_DEFAULT, target/value,
rule ID/version, rationale, basis revision ID/hash and candidate hash. Effective
Assumed states additionally retain RuleSource time/rationale; registry snapshot
and policy_sha256 bind exact contextual policy content.

Do NOT render base_prompt.prompt_text as the final result: it is the immutable
IFP5 input evidence and may retain native BLOCKED/audit history. It is not handed
to downstream execution. IFP6 prompt_text contains only latest effective facts,
active constraints and explicit left-unspecified targets; old values stay audit.
CompiledPrompt is used internally for validated state traversal, never returned
as an authoritative substitute or generation instruction.

## Retries, edits, failures and currentness

- Exact same body+request_id+principal:200 replayed=true, identical stored artifact.
- Same ID with changed body/principal:409 idempotency_conflict.
- New command with stale revision/cycle/plan/history:409 stale_completion_frame.
- Editing or answering after completion: existing API remains unchanged. GET
  current returns409 completion_invalidated. Fetch conversation, explicitly ask
  again, persist a new choice, and submit a new request/frame. Defaults recompute
  from current canonical state, not prior overlays. User values supersede defaults.
- Retrying an OLD completed command after editing returns its immutable history
  with is_current=false; never show it as the current design. A later YES likewise
  supersedes earlier NO even if the canonical frame itself did not change.
- Pending KEEP:409 pending_keep_consent. Use the existing separate explicit release
  API; NO cannot accept it. Active LOCK is never rewritten by a default.
- Contradiction:409 conflicting_evidence; mandatory missing user choice:
  409 mandatory_decision_unresolved. Resolve via existing clarification/correction.
- Wrong completion source choice/user Message:422 invalid_completion_intent;
  Pydantic malformed request:422. Unknown/foreign session/message:scoped404.
- Stored hash/source mismatch:500 invalid_completion_history; do not blindly retry.
- Transient serialization/deadlock/unique race:409 completion_transaction_conflict;
  retry the exact body after a fresh read. Non-transient database failure:
  503 completion_storage_unavailable, including a missing migration.
- GET and POST responses are no-store/private. Authentication/membership is checked
  again inside the transaction; a revoked member cannot replay old artifacts.

## Actual Input -> Output proof

Test-only API path: yellow-gold engagement ring, oval diamond, unknown dimensions;
actual contextual UNKNOWN then SKIP answers; YES; prong-setting correction; NO.
The durable result is IFP6 with exact frame, preserved canonical revision and a
TEST-ONLY 8×6×4 Assumed overlay. Same request replays the same artifact; server
restart restores it. Correction to platinum and9×7×4 changes current canonical
values, invalidates prior completion and a new NO produces an IFP6 with explicit
9×7×4 and platinum, no previous8×6 assumption or gold material as active facts.
Independent yellow color remains accepted unless the user changes it: material
and color are distinct existing canonical fields; this task does not invent a
Parser cancellation rule. Old artifacts remain immutable and marked non-current.

Additional tests cover no-default completion; pending KEEP refusal then explicit
REJECT of the change followed by completion; active LOCK; scope/auth; request-ID
conflict; source tampering; failure after flush rolls back; stale cached SQLite
revision cannot be written back by the writer reservation. No paid provider call.

## Functional Definition of Done / limits

Technical implementation is not independent acceptance or production policy review.
Native UNKNOWN/SKIP obligations are completed only through the explicit approved
eligibility rules; missing user_required or conflicting evidence remains blocked.
F05/IFP4, F06/IFP5, source hashes/frontiers and canonical revisions stay unchanged.
The new final artifact has its own integrity/readiness validation, not a relabelled
old IFP. UI must explicitly adopt these routes and source/currentness fields.

Local proof uses existing fake authentication, TEST-ONLY Knowledge and temporary
SQLite. PostgreSQL lifecycle/migration/check is implemented under the existing
fresh CI guard, but NOT VERIFIED locally without that authorized service. No real
users, preprod data, provider credentials or shared migration were used. Frozen
PG tests' exact expected head assertions now name0019; their guards remain intact.
No visualization/downstream handoff6 is enabled; old consumers reject unknown6.

See the Draft PR for exact source SHA, focused commands/results, failed-development
receipts and test-execution ledger. Do not substitute green CI for functional review.
