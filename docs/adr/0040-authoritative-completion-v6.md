# ADR0040 — Opt-in durable completion and authoritative IFP6

Status: Draft implementation for independent review; activation and shared migration
require separate Owner approval. New development branch; PR155 remains unchanged.

## Context / authority

The Owner's follow-up explicitly authorizes implementing additive durable/public
contracts inside a Draft PR, rather than another review-only selector. It does not
authorize merge, deployment, shared DDL or silently approved professional defaults.
F05/IFP4 and F06/IFP5 cannot become READY by relabelling native unresolved evidence.
An explicit NO is a new completion action, not a clarification or an empty GET.

## Decision

Keep canonical Product State immutable. Apply only reviewed, context-matched
missing-value defaults in a fully validated effective overlay using existing
Assumed/RuleSource, labelled AI_DEFAULT with source revision/policy hashes.
A new IFP6 embeds the immutable IFP5 basis, canonical revision, registry snapshot,
effective state/parameter provenance and active constraints. Active prompt_text
is rendered only from current effective facts and constraints, never chat replay
or old descriptive wording. base_prompt is audit evidence, NOT active prompt text.

Completion-specific eligibility is explicit registry data, scoped by jewelry type
and known canonical prerequisites. Existing known, confirmed, not-applicable, KEEP
and LOCK values are never replaced. Unknown/SKIP does not grant user confirmation.
After NO, approved default_or_omit information gaps may remain unspecified; the
prompt explicitly prohibits invention. default_only gaps require a valid matching
default. user_required targets still require a real answer. Material alternatives,
competing facts, blocking unbound requests and pending KEEP consent cannot be
discharged by completion. Nonblocking unaccepted requests remain unaccepted source evidence; only actually
missing effective values are left unspecified; NO does not turn them into facts or silently erase
source history. Native criticality is preserved. Legacy blockers need existing compatibility proofs.

No original frontier/answer/blocking flag is rewritten. The separate IFP6 validator
recomputes policy selection, overlay, omission coverage, rendering, readiness and
provenance. All OPEN native unresolved details remain in the sealed basis; every
blocking target must be covered by the completion policy or construction fails.
This is not an IFP4/5 readiness override. Old readers do not silently accept6.

## Storage and transactional safety

Migration0019 adds append-only prompt_completion with session/organization,
revision/cycle/Message/principal FKs, unique(session,request), unique(session,sequence),
request hash, immutable source/policy/result evidence and creation time. PostgreSQL
rejects UPDATE/DELETE. Online downgrade refuses to erase history. SQLite metadata
is disposable test infrastructure; stored hashes/reconstruction detect corruption.

Completion reuses organization/membership + session-first locking and locked_reader.
SQLite reserves a writer using SQL column=self (not a cached revision value), then
refreshes the row. Full-frame CAS includes revision, cycle, plan and history root.
Build, final result verification, insert/flush, stored-source reconstruction and
response-model validation occur before one commit. Any failure rolls back the row;
no canonical revision/cycle or provider work is performed by completion.

Replay is durable, scoped to session and original principal. Different request
content under the same request ID returns409. Exact retries return stored bytes;
a replay after editing is marked is_current=false. A new accepted edit/answer/plan
frame invalidates current completion without mutating the original record.
YES is retained in the same ledger and makes the newest result EDITING. Sequence
numbers, not equal timestamps/random UUID order, define latest completion.

## Activation / alternatives / consequences

Runtime is disabled by default. Enabling requires PROMPT_COMPLETION_ENABLED=true,
an explicit approved registry file and exact registry SHA256. create_app supports
a typed registry injection for TEST-ONLY integration. The checked-in initial
policy set is PROPOSED and rejected at activation; no numeric defaults ship there.
Its professional values/contexts require actual Owner/domain review. Quantitative
8×6×4 examples exist only in tests with explicit TEST ONLY rationale.

Alternatives rejected: overwrite canonical revisions invisibly; use a blanket
preset; mark IFP4/5 READY; persist CompiledPrompt as final; infer NO from GET;
store a browser-only completion; create a second message or authorization system.

The new API/IFP/storage versions need independent review and approved rollout.
No frontend, worker, provider, visualization, production or live database change.
PostgreSQL execution proof is gated by the existing independent disposable-service
check (including job identity and two-hour freshness); no arbitrary DB is tested.
See completion-api-v1.md for UI integration and evidence/limitations.
