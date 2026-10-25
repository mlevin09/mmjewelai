# ADR 0032: Introduce Knowledge Library Contract v1.1 as a parallel runtime

Status: **Accepted**  
Date: **2026-10-25**

## Context

Knowledge Library Contract v1.0.0 is an immutable production-oriented contract whose compiler,
runtime hash, durable artifact shape and ACTIVE evidence are already used as lineage anchors.

The P0 content baseline and Jewelry Design Schema v1.1 expand Product State target ownership from
30 current Knowledge-policy target families to 148 Product State target families. Extending the
v1.0 target grammar in place would change the meaning of existing source bundles and could alter
historical runtime hashes.

## Decision

Introduce Knowledge Library Contract v1.1.0 as a **parallel versioned runtime**.

The v1.1 implementation has separate:

- source bundle identity;
- policy target grammar;
- deterministic compiler and manifest;
- compiled runtime type and SHA-256 identity;
- policy runtime;
- durable artifact store;
- production-validation report;
- ACTIVE envelope and promotion function;
- Prompt Enrichment entry point.

The existing v1.0.0 classes, compiler, storage and activation path remain unchanged.

## Target boundary

Knowledge Library v1.1 accepts only the frozen Jewelry Design Schema v1.1 Product State target
grammar. It may address stable repeated identities with:

- `{group_id}`;
- `{component_id}`;
- `{element_id}`.

It explicitly excludes non-Product-State layers such as Reference Binding, AI Generation State,
Output Profile and Visualization Verification Result.

## Activation boundary

Compilation never activates a release.

A v1.1 release can be represented as ACTIVE only when one exact compiled runtime is accompanied by
a production-validation report whose complete required check set passes and whose package/version/
runtime hash exactly match the runtime.

EXPECTED_GAP does not count as PASS.

P0-21 implements the capability but does not create or promote a production v1.1 catalog.

## Compatibility

Historical v1.0 bundles continue to validate and compile under Contract v1.0.0 only. Their runtime
serialization and hash semantics are not widened by this ADR.

A v1.1 source package must use a different explicit contract identity and should use a separately
versioned immutable artifact identity. Durable storage remains fail-closed if a package/version path
already contains different canonical content.

## Consequences

The JewelAI runtime can now consume reviewed Knowledge policies for additive Schema v1.1 Product
State targets without weakening v1.0 lineage.

Content availability does not imply production activation, and the existence of all 148 possible
target families does not imply that reviewed policies have been authored for all 148.

Future catalog growth can occur incrementally as reviewed evidence/policies become available.
