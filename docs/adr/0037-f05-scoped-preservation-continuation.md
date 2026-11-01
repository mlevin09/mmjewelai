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

The approved target additionally requires durable atomic decisions/re-anchoring,
current versioned outputs, all R2 HTTP scenarios, isolated PostgreSQL proof and
exact-head CI. No schema migration is introduced here. The existing-row/no-DDL
approach still requires actual disposable PostgreSQL validation, not an assumption
from JSON capacity. New readers must remain after disabling new writers.

Default L, F activation, Knowledge content/releases, provider adapters, workers,
shared/preproduction/production infrastructure and deployments remain unchanged.
Source4 is not authorization to bypass existing preparation consumers.
