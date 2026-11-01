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

Current implementation introduces schema-derived preservation primitives, strict
command/context variants, the separate parser interpreter, scoped read-only native
history bootstrap, and narrow compatibility proof derivation. These are not yet a
complete continuation admission/correction/answer/resume HTTP workflow. The Draft
PR must disclose missing integration and tests until that work is complete.

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
These pure checks are not a live consent endpoint or proof of the KEEP_RELEASE
transaction lifecycle. Explicit admission now persists Cycle3/Plan3 and supports
strict admission-prefix replay as described below; durable corrections, answers
and resume remain unfinished.

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

This admission implementation does not establish the complete F05 workflow:
Answer3, Correction3, Resume3, bound KEEP_RELEASE HTTP consent, ordinary native
answer protection and D2 composition with new decisions still require delivery.
The approved 36+18 matrix cannot be marked complete from admission tests alone.
