# P0-18 Runtime Adoption & Persistence Integration

Status: **IMPLEMENTED ON INTEGRATION BRANCH — CI/DEPLOYMENT PENDING**  
Date: **2026-10-25**

## Purpose

P0-18 adopts the P0-17 runtime contracts at the persistence/API boundary without
silently switching existing sessions from Jewelry Design Schema v1.0.0 to v1.1.0.

## Design Schema adoption policy

Existing sessions remain pinned to their stored `design_schema_version`. Normal
revision CAS requires child and parent to use the same schema version.

Persistence now supports one explicit atomic v1.0.0 -> v1.1.0 migration primitive.
The migration:

- requires the currently authoritative v1.0 revision;
- appends a new immutable revision with revision number +1;
- keeps the same design ID and sets the old revision as parent;
- updates the session schema pin and current revision in the same transaction;
- never rewrites or deletes the historical v1.0 snapshot.

The migration primitive is intentionally **not exposed as a public API action in
P0-18**. Parser/Question/Rules coverage for the 118 additive v1.1 Product State
targets is not yet complete, so enabling arbitrary customer-session migration would
create a partially supported runtime. Public sessions therefore continue to start
on v1.0.0.

## Reference Binding persistence

Migration `0015_reference_verification` adds append-only Reference Binding storage.

Before commit, persistence verifies:

- organization/session ownership;
- the referenced Asset exists in that exact scope;
- the Asset is a reference Asset;
- the frozen v1.0.0 runtime model validates;
- repeated writes with the same binding ID are idempotent only for identical
  canonical content.

Reads revalidate the payload and relational mirrors, including asset ID and content
hash.

The API exposes create/list/get endpoints under:

`/sessions/{session_id}/reference-bindings`

## Visualization Verification persistence

The same migration adds append-only Visualization Verification storage.

Before commit, persistence verifies:

- organization/session ownership;
- GenerationRun belongs to the session;
- optional Asset and previous Asset belong to the same tenant/session;
- optional Product State revision belongs to the session;
- the frozen v1.0.0 verification runtime validates;
- duplicate verification IDs are idempotent only for identical content.

Reads revalidate all lineage mirrors and content hashes.

The API exposes create/list/get endpoints under:

`/sessions/{session_id}/visualization-verifications`

P0-18 stores verification evidence; it does not add or invoke a verification model.

## Contract correction found during adoption

P0-18 found and fixed a P0-17 implementation defect: the generated Python source
for `FeatureBinding.observability` contained escaped newline text and did not
faithfully implement the frozen schema. The runtime field is now syntactically
valid and required, matching Reference Binding Contract v1.0.0.

## Security and tenancy

Both new persistence paths use the existing organization-scoped session boundary.
Cross-organization reads return not-found semantics and cannot retrieve a binding
or verification record by identifier alone.

No user-controlled organization ID is trusted without the existing authorization
boundary.

## Migration

Alembic head advances:

`0014_clarification_plans -> 0015_reference_verification`

The migration is additive. It creates two new tables and does not rewrite existing
rows.

## Deliberately deferred

- public API action to migrate a session to Schema v1.1;
- default creation of new sessions on v1.1;
- Parser/Question/Rules coverage for all additive v1.1 fields;
- Knowledge Library v1.1 durable compiler/ACTIVE promotion;
- automatic generation of Reference Bindings from image understanding;
- automatic execution of Visualization Verification;
- production or preproduction deployment.

These are runtime-adoption/release tasks, not Knowledge Library content gaps.
