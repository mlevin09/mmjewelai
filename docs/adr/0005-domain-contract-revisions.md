# ADR 0005: Typed immutable domain snapshots and explicit transitions

Status: Accepted for Issue #1 implementation. Date: 2026-09-20.

## Context
Schema v1 must preserve provenance and locked constraints without coupling the domain to a database,
API or provider. The original root Python configuration targets missing V1 application files.

## Decision
Create the isolated packages/domain distribution using Pydantic (the repository's existing validation
library choice). Export a JSON Schema draft 2020-12 wire contract. Use frozen models and immutable
tuples throughout snapshots; explicit, derived, assumed, unknown and inapplicable variants carry
different required evidence. Confirmation and lock remain independent of origin.

Use UUID revision tokens, parent references and numbered immutable snapshots. Domain functions
compare the caller's expected token with the supplied current snapshot, reject edits to locked
leaves (including deletions), and audit confirm/lock/unlock operations. Stable side-stone group IDs
prevent collection reordering from retargeting locks. Changed values require reconfirmation.

## Alternatives
A mutable dictionary loses validation and makes lock enforcement fragile. A single state enum
combining origin and lock loses provenance when values become locked. Database-only locking cannot
validate offline proposals and would prematurely implement persistence.

## Consequences
JSON Schema validates structure, units, states and basic lineage. Python additionally checks semantic
uniqueness and cross-field time/identity relationships; transition functions check history-dependent
rules. A schema-valid snapshot is not proof that a requested transition is permitted.
Future persistence must atomically compare-and-swap the stored revision token; these pure functions
cannot prevent two concurrent processes from saving against a stale database read.
Domain IDs are syntax-checked only until the dictionary issue supplies approved vocabulary.
NotApplicable is an explicitly sourced user declaration; later rules decide whether it is permissible
for a required field. No measurement inference, readiness policy or production defaults are included.

## Validation
Independent JSON Schema and Python checks over shared valid/invalid fixtures; unit tests for finite
units/counts, provenance, deep immutability, lock removal/rename attacks, stale edits and full
unlock/edit/reconfirm/relock lineage. Test-only jsonschema is justified as an independent validator.
