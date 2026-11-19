# ADR 0047 — US-01 dual interpretation and commit-aware natural reply

Status: implementation for independent review in Draft PR #185; not a release,
activation, deployment or independent acceptance. EN MASTER, 2026-11-19.

## Context and authority

Owner-confirmed Architecture v0.5 and D3 require the installed machine LLM to
interpret original text, with Parser 1.3 independently interpreting that **same**
text. D2-A requires a validated scoped State commit and receipt **before** the
natural reply. D5-B permits development with incomplete qualified Library coverage;
recognition or recommendations never constitute user consent.

References: [Architecture v0.5](https://docs.google.com/document/d/1ACoRQmcR23R9f512H77UKS_IhEfTA343gig5ej7XeeY/edit),
[Boundary v1.1 EN](https://docs.google.com/document/d/1gNM4M4acB8VljTWOkry_wWogZbuOSz6yPb3RG3GXEZw/edit),
[stories](https://docs.google.com/document/d/172ZGSU9G8N2WP6Aq7obbjQ4cnlMs7ST02VQM1lvPsog/edit).
Unapproved portions of proposed Boundary v1.1 do not supersede approved v1.0.

ADR 0046's schema1 receipt is immutable and permits only deterministic fallback.
It cannot represent D2-A delivery after commit. On 19 November the Owner explicitly
approved the narrow additive versioned turn receipt and code-only migration in this
PR, retaining old receipt 0022, original bytes/hashes and readers. This supersedes
ADR 0046's single-transaction reply construction **only for the new schema2 path**.
It does not reinterpret or mutate old sessions. Shared migration is not authorized.

## Decision

Reuse the same backend, authorization, canonical DesignRevision, Parser, qualified
Library matcher, Matrix/Policy and revision-CAS machinery. No new service, Parser,
canonical store, provider selection framework or professional catalog is created.

1. Schema2 first-turn input retains exact original text, turn identity and expected
   revision. Optional typed product selection remains separate from text; edited
   transcript provenance is explicitly user-reported, not proof of ASR capture.
2. `QwenConversationAdapter.interpret` sends original input, scoped current State,
   role/locale and typed selections to the existing llama.cpp chat-completions
   interface. It does not send Parser candidates or preselected semantic answers.
   `SemanticProposal` is an internal untrusted versioned DTO, not Parser evidence.
3. The existing current Parser independently reads original text. SO arbitrates
   intent, source spans, DIRECT qualified mappings/existing Dictionary, component
   ownership, competing values and existing State. A missing Parser candidate is
   not an automatic veto: independent exact source/mapping proof can suffice.
   Agreement is not authority. Each proposal receives ACCEPT, CLARIFY or NO_COMMIT;
   Matrix can still block source-eligible changes before State writes.
4. Only the existing three approved initial bindings are writable here: product
   type, product-body metal material and adjacent metal color. The existing source
   ownership proof is shared, without changing historical Parser governance.
   Unallocated sapphires/counts are retained as evidence with unresolved attachment
   and quantity scope. No group, EACH/PAIR/TOTAL, weight, origin or shape is guessed.
5. One transaction locks the scoped session, checks current artifacts/revision and
   first-turn eligibility, appends original Message, optional next revision and
   immutable input/interpretation/Matrix receipt. Full read verification runs
   before commit; a rejected result leaves no partial source or State.
6. After commit, SO reads the actual retained revision. The reply request contains
   committed facts plus accepted/unresolved outcomes and versioned grounding
   references. The model authors natural wording, not a selected deterministic
   template. Critical validation checks recognized jewelry facts, quantities,
   components, confirmation/protection and source-only ambiguity against State.
   Successful text is retained unchanged; invalid/unavailable output gets an
   explicitly labelled fallback, never a model-success claim.
7. Delivery is write-once in a second transaction, bound to input/revision/context
   hashes. PostgreSQL rejects source mutation, delivery overwrite and deletion.
   Pending delivery is distinguishable from committed input/State. Repeating a
   turn cannot append a second State revision or regenerate a delivered answer.
   An explicit identical POST may finish a pending reply only; GET never invokes
   the model. Concurrent delivery returns the retained winner, never an unsaved draft.
   GET and process restart verify source/Matrix/revision/provenance and return the
   exact retained response without invoking a model. Downgrade refuses retained data.

The added `initial_conversation_turn` stores a derived audit/delivery receipt,
**not** a second Product State. Existing specification revisions remain authoritative.
Legacy F04 correction/planning entrypoints refuse this new workflow rather than
silently executing an older story. Multi-turn continuation is separate work.

## Runtime and security

The adapter reuses existing httpx and llama.cpp `/v1/chat/completions`, with explicit
model/digest/build pins, private literal-IP endpoint, no URL credentials, no redirects,
no automatic retries and bounded response size/tokens/time. It has no VM-lifecycle,
cloud credential, shell-execution or State-write capability. Provider errors expose
bounded codes, never raw bodies/messages. No Google conversational adapter or
Google-first understanding fallback is selected for schema2. Legacy routes retain
their existing behavior. Configuration is opt-in and disabled by default; no cloud,
production, worker, IAM, firewall or deployment configuration changes are included.
A configured artifact pin is not remote attestation; release qualification must
verify the actual running model and the authorized private connection.

## Alternatives and consequences

- Rewriting receipt1/0022 or assistant text into user Messages breaks immutable
  history and is rejected.
- Model or Parser direct writes bypass source/Matrix/State authority and are rejected.
- Calling a model under database locks makes network failure a transaction/liveness
  risk and is rejected.
- Suppressing post-commit failures as apparent success is rejected. Degraded delivery
  remains explicit; a valid State commit is not undone by model failure.
- A vocabulary whitelist/template selector cannot establish natural conversation and
  is not the successful-model path. Critical checking remains bounded by current
  extractors, so arbitrary professional prose is not claimed fully verified. No
  ungrounded professional recommendation is qualified by these tests.

Focused mocked and real-model receipts must be distinguished. SQLite is not
PostgreSQL trigger qualification; only the unchanged disposable-PG gate can authorize
PG DDL. Hosted exact-head checks, model quality, coordinator-owned UI integration,
private runtime connectivity, live authentication and deployment are separate gates.
No coverage/clarification-answer engine, Final Brief confirmation, IFP handoff, image
provider, new research campaign or Full Regression is introduced.

## Owner-directed verification boundary, 19 November 2026

The Owner stopped further Qwen probing/configuration work and directed continued
functional integration. The VM is TERMINATED; unused additional inference calls
will not be consumed. Current mocked HTTP/SQLite tests establish orchestration,
not final real-model quality, interactive latency or deployed private connectivity.
The existing R1 operational reference is not a professionally qualified winning
preset. No server configuration or deployed runtime is changed by this PR.

Compact quoted proposals retain the original LLM evidence. SO derives a span only
from one exact occurrence; repeated/missing quotes require clarification. Component
ownership is checked for each source occurrence, including repeated equal values.
Source-only mentions cannot justify false claims that unresolved facts were saved.
