# ADR 0037: F05 scoped preservation and retained-profile continuation

Status: Owner-approved R2 contract; implementation in progress. Date: 2026-11-01.

## Context

An explicit center-stone correction and ordinary preference acceptance can change a
preserved value while the original generic KEEP remains in the final description.
Historical L output can also remain blocked after an accepted correction. Changing
the shared historical parser would invalidate retained F04 replay.

The Owner approved T1–T7 against the six-artifact
[F05 R2 technical contract](https://drive.google.com/file/d/19fR_ebYNdZDj_--AuWUp0g59igFeIktK/view)
(SHA-256 `71c1e0811f49c9022466d2535d36d50c436c999a2adabf7c0e2e5947826083d3`).
The [independent contract review](https://drive.google.com/file/d/1LY4LdhCypCVOzcHtu5SBVMNfnJCzx-EH/view)
closed the three contract P1 findings. Contract approval is not implementation
acceptance, release activation, migration permission or deployment authorization.

## Decision

Derive whole-center KEEP coverage from the retained canonical Stone model: eight
wrappers in schema 1.0 and fourteen in schema 1.1, including absent/Unknown/N/A.
Keep the six existing parser-correctable targets separate from protection scope.
Specific wording remains specific; overlapping roots all participate.

A conflicting supported delta requires separate typed, value-bound consent. On
acceptance, only that field changes and is re-anchored under every applicable root.
Other facts, root sources, provenance and LOCK remain intact. Native clarification
actions cannot serve as KEEP-release consent. Confirmation does not itself mark a
canonical value confirmed or unlock anything.

New request/evidence versions compose with the retained L or trusted F profile.
The old parser and transitive helpers remain unchanged; the explicit parser 1.2
path cannot reinterpret retained 1.1 records. Native question actions and the
existing `REJECTED/parser_rejected` result retain their meanings.

Legacy compatibility is an explicitly selected read-only projection. It must prove
the exact original UNKNOWN and actual accepted same-target transition, or exact
accepted body-metal source-span coverage. It must preserve unrelated blockers,
original records/hashes and profile/release pins. It is not implicit L-to-F.

Store an acyclic FrontierCore before hashing Plan3; seal the current frontier only
afterward. Exact source, owner, canonical ancestry and transaction-frame validation
remain required. Hash equality alone is not authority. Duplicate handling occurs
under current tenant authorization before freshness CAS for genuinely new work.

## Alternatives

Deleting a KEEP, permanently excluding a field, interpreting ordinary ACCEPT as
release, or broad cancellation would exceed the approved one-shot semantics.
Globally editing the old parser or ignoring historical flags invalidates replay or
discards actual unresolved intent. A new catalog, canonical state, clarification
engine or persistence ledger is unnecessary.

## Consequences and implementation boundary

The implementation reuses schema-derived preservation primitives, strict
command/context variants, the separate parser interpreter, scoped native-history
replay and narrow compatibility proofs. Explicit admission, corrections, native
answers, typed KEEP release and explicit resume use the same existing rows and
session-first transaction boundary. Functional acceptance remains independent of
implementation and CI; the Draft PR records the actual scenario evidence.

Explicit `GET state?workflow_version=3.0.0` now provides a non-admitting read-only
preview: retained L/F pins, current causal frame, protection evidence and Description3.
Explicit `GET final-output?output_version=4.0.0` requires the exact current frame's
`If-Match`; L additionally requires `projection=jewelai.legacy-l.compat/1.0.0`.
The projection can discharge only independently proved historical blockers. Original
UNKNOWN/DEFERRED records remain unchanged, including their blocking flags, and old
default output routes retain their meanings. No GET creates a plan, offer or event.
IFP4 and handoff4 retain the current frame/protection/readiness evidence; F also
retains its sealed frontier, availability and causal definitions. Preparation1/2
explicitly reject source4 with `unsupported_source_version`; no provider execution
or legacy source downgrade is added. These previews do not confer admission.

The approved target additionally requires durable atomic decisions/re-anchoring,
current versioned outputs, all R2 HTTP scenarios, isolated PostgreSQL proof and
exact-head CI. No schema migration is introduced here. The existing-row/no-DDL
approach still requires actual disposable PostgreSQL validation, not an assumption
from JSON capacity. New readers must remain after disabling new writers.

Default L, F activation, Knowledge content/releases, provider adapters, workers,
shared/preproduction/production infrastructure and deployments remain unchanged.
Source4 is not authorization to bypass existing preparation consumers.

The pure release-evidence layer implements the approved intent, binding, offer and
decision DTOs and derives current anchors only after an independently verified
typed command and canonical transition. Requested-value digests use
`H('jewelai.KeepRequestedValue/1.0.0', canonical_value)`; wrapper anchors separately
retain the complete sourced canonical wrapper. Accepted facts retain the original
correction MessageSource while the EDIT event records the typed authorization
MessageSource. All applicable roots receive the new anchor; other wrappers and
original roots remain immutable. A later different value requires a fresh binding
and decision. Rejection closes only its logical request. Independent transitions
retain anchors and invalidate earlier offers without discarding pending requests.
The pure checks are used only after the runtime has verified the actual scoped
source, current frame, original intent and offer. The persisted workflow replays
the actual correction and authorization against canonical ancestry rather than
trusting an envelope hash alone.

### Explicit admission implementation

`POST /v1/sessions/{session_id}/prompt-enrichment/continuation-admissions` accepts
only AdmissionRequest1 and requires the server-side continuation capability,
which defaults to disabled. A membership recheck and session lock precede source
validation, duplicate lookup and full-frame CAS. Original native L/F history is
replayed under the unchanged native decoders before a new Cycle3/Plan3 is staged.
The inner native result is retained under its original version, with no relabelled
Plan2, Answer2 or IFP3. Canonical state, release and artifact pins are unchanged.

Admission command/source, previous head, parser transition and exact native
planning evidence are stored in Plan3. The current plan hash is not embedded in
its own cycle/core. Replay validates actual source text and the frozen native
prefix, recomputes both envelopes and only then seals the current native frontier
and frame. It rejects mixed or incomplete post-admission intervals. Prefix reads
reuse the caller's transaction without widening the historical interval.

Cycle/plan insertion and current output validation occur in one transaction.
Plan insertion or output/capacity failure rolls back the entire unit. Duplicate
admission returns the original committed frame before checking freshness; another
admission identity is rejected. Reused identity with changed payload is rejected.
Default legacy state/final-output and native writers reject admitted sessions
with `unsupported_workflow_version`; exact historical decoders remain available
to the replay path. Explicit current reads are non-writing and continue to work
when new admissions are disabled. No configuration enables F05 in a live runtime.

### Durable continuation commands

Existing correction and clarification-answer routes select exact request3 variants
without changing native request1/2 interpretation. A conflicting supported single
field creates Correction3 plus an immutable intent and current offer, without a
canonical revision. Several canonical deltas overlapping KEEP defer as one batch.
An ordinary native ACCEPT/SELECT cannot authorize another preserved value.

KEEP_RELEASE ACCEPT records Answer3, a one-field EDIT, Cycle3 and Plan3 atomically.
The value cites the original correction; the EDIT cites the distinct typed consent.
Every applicable root is re-anchored and every other canonical wrapper is retained.
REJECT closes only its own logical request. Subsequent events stale prior offers
but retain pending intents; explicit resume3 allocates a new binding. An already
current requested value is re-offered for REJECT-only closure, never fake APPLIED.
Native F resume retains the existing OPEN/DORMANT, ownership and re-offer policy.

Every command uses authorization, exact duplicate lookup, full-head CAS, and
precommit current-output verification inside one transaction. Source/revision/
cycle/plan insertion failure rolls back the whole unit. Scoped readers may detach
session rows; the writer reacquires its already locked attached row before updating
the canonical pointer. No provider publication is performed in the transaction.

The L compatibility projection can cite a verified KEEP-release Answer3 only for
its actual accepted target and original positive correction. Original UNKNOWN
flags and hashes remain untouched. GET never creates an event, binding or offer.
Readers remain available with continuation writers disabled. New writes require
the explicit server-side capability, which remains disabled by default.


The internal Parse1.2 → ParsedEvaluation3 bridge invokes the existing
ParserProposal/Matrix evaluator with explicitly selected new readers/builders.
Frozen defaults remain Parse1.1 and evaluation1/2. It binds actual Message
identity/time/session, schema, retained context and release; returns source-backed
proposal/disposition/native-rule evidence with its own hash; and performs no
canonical mutation or network call. Unsupported, negative and uncertain input
cannot become affirmative updates. Correction3 persistence and typed release are
separate authenticated runtime responsibilities; a parser/Matrix match is never
consent.


### Canonical Matrix versus candidate evidence

The version3 correction keeps the actual Parse1.2 / ParserProposal / Matrix
candidate evaluations before and after the canonical transition as immutable
evidence. Matrix eligibility is not commit authority: an explicit numeric
candidate can be APPLIED by Matrix policy while its canonical update is still
withheld for KEEP consent or whole-batch deferral. Cycle3 therefore projects its
current native Matrix from the actual committed canonical revision through the
existing enrichment compiler, without replaying uncommitted candidate proposals
as current facts. No Matrix cell or historical policy decision is relabelled.
Current constraints, pending requests and the native question plan retain their
separate sourced evidence. Answer3 likewise derives the next current projection
from its actual committed canonical child. This preserves the approved authority
boundary for scalar, dimensional and other supported values equally.


Native question trigger references reuse the existing immutable source-reference
DTOs with the actual version3 record ID/hash and previous Plan3 binding. They are
not relabelled legacy results or plans. ResumeResult3 is derived from the sealed
Plan3 and only its requested emitted questions; its hash is distinct from the
plan hash. Result derivation and envelope validation precede the atomic commit.
Exact committed retries remain readable under current tenant authorization when
new continuation writes are disabled; new work still fails the capability gate.
A historical parser1.1 span truncated before an explicit center-shape qualifier
is scoped using that actual governed source phrase, without rewriting the saved
span/parse or inspecting a later independent assertion.

### Native L obligations across admission and Answer3

Current L decision audit reuses the existing source-bound effective-correction
policy over the fully verified native prefix and version3 events. A neutral
admission bridges only the exact retained native questions and unasked evidence
at the same canonical revision. Native Answer3 can resolve its own original
question; candidate IDs, target/value coincidence or a later revision alone are
insufficient. A new correction interrupts the answer-only causal chain. The
original correction outcome, blocking evidence and hashes remain immutable;
only the current derived audit changes. F retains its existing frontier policy.

This does not broaden L2 contextual coverage: a Knowledge-only residual without
an approved exact binding, such as the unbound `white` mirror in a full repeated
S0 clause with the optional TEST-ONLY binding, remains unresolved. No new catalog
mapping or professional applicability decision is introduced by F05.
