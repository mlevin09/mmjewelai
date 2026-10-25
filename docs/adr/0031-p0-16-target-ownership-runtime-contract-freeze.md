# ADR 0031: Freeze P0-16 target ownership and auxiliary runtime contracts

Status: **Accepted**
Date: **2026-10-25**

## Context

P0-13 closed the Knowledge Library content baseline at 166 content-governed target/path families.
P0-14 established that the current Jewelry Design Schema v1.0.0 and Knowledge Library Contract v1.0.0 do not represent that full content baseline. P0-15 classified the 166 targets by runtime owner and drafted an additive Product State vNext plus separate Reference Binding and Visualization Verification contracts.

The remaining gate was source reconciliation. The individual historical generated JSON/MD files for P0-1 through P0-9 are not present in the current workspace. However, the preserved previous-chat transcript, current P0-10/P0-13 artifacts, and current repository contracts preserve enough evidence to reconcile the target counts and semantics.

A hidden historical identifier must not be invented merely to claim byte parity.

## Decision

Freeze P0-16 under the following rules.

1. The v1 content baseline remains exactly **166** target/path families.
2. Target ownership is frozen as 30 current Product State v1 targets, 118 additive Product State v1.1 candidates, and 18 targets outside Product State.
3. Jewelry Design Schema 1.1.0 is reserved as an additive minor version. P0-16 freezes target ownership and migration invariants; executable Pydantic/runtime implementation is a separate step.
4. Feature-level reference semantics are frozen in Reference Binding Contract v1.0.0.
5. Generated-media QA semantics are frozen in Visualization Verification Result Contract v1.0.0.
6. Existing Jewelry Design Schema v1.0.0 snapshots remain immutable historical artifacts.
7. No content record, source, or policy automatically populates a new Product State field.
8. No Knowledge Library release becomes ACTIVE because of this freeze.

## Source-reconciliation rule

Each target receives one of four source statuses:

- REPOSITORY_EXACT
- TRANSCRIPT_EXACT
- ARTIFACT_EXACT
- CANONICALIZED_FROM_EXPLICIT_SOURCE_SEMANTICS

The last category is deliberate. It means the preserved source clearly defines the semantic item and the total accounting, but does not expose a historical dotted identifier. P0-16 establishes the canonical identifier prospectively and does not claim hidden historical byte parity.

## Arithmetic reconciliation

56 original Matrix + 3 P0-1 + 10 P0-2 + 2 P0-3 + 1 P0-4 + 5 P0-5 + 16 P0-6 + 27 P0-7 + 0 P0-8 + 31 P0-9 + 15 P0-10 + 0 P0-11 + 0 P0-12 + 0 P0-13 = **166**.

## Contract boundaries

Product State stores authoritative or explicitly governed design state. P0-16 does not move reference instructions, camera/presentation parameters, verification results, or subjective interpretation metadata into Product State.

Reference Binding links an existing asset to feature-level semantics KEEP, CHANGE, LOCKED, INSPIRATION, or UNKNOWN. A binding records instruction/evidence and does not mutate Product State by itself.

Visualization Verification records evidence about generated media with PASS, FAIL, UNVERIFIABLE, NOT_APPLICABLE; severity BLOCKER, MAJOR, MINOR; and actions ACCEPT, RETRY, ASK, CAD_3D_FALLBACK, DO_NOT_CLAIM. It is not jewelry state and cannot establish manufacturing truth.

## Compatibility

The 1.1 Product State direction is additive. Historical 1.0.0 snapshots are never silently rewritten. A future implementation must provide explicit versioned models, JSON Schema, migration/compatibility tests, compiler target grammar updates, and Prompt Enrichment integration.

## Consequences

P0-16 closes source reconciliation and schema ownership governance. The next engineering slice can implement the frozen contracts without reopening content scope.

Remaining implementation work is not a content gap: executable Jewelry Design Schema 1.1.0, target grammar/compiler update, Reference Binding runtime model, Visualization Verification runtime model, migration/compatibility tests, and Prompt Enrichment/generation-lineage integration where approved.
