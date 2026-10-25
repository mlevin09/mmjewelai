# P0-17 Runtime Contract Implementation

Status: **IMPLEMENTED ON FEATURE BRANCH — NOT ACTIVE / NOT DEPLOYED**  
Date: **2026-10-25**

## Purpose

P0-17 implements the runtime contracts frozen by P0-16 without rewriting historical
Jewelry Design Schema v1.0.0 snapshots or changing the existing Knowledge Library
v1.0.0 ACTIVE/durable-artifact lineage.

## Implemented

### Jewelry Design Schema v1.1.0 runtime models

A separate `DesignRevisionV1_1` contract implements the additive Product State
extensions selected in P0-16. Existing `DesignRevision` remains pinned to
`schema_version=1.0.0`.

The implementation includes typed nested structures for:

- stone semantic extensions;
- side-stone population semantics and sieve metadata;
- prong, halo and pavé state;
- alloy/coating/surface-treatment and stable-ID metal components;
- product-family construction and dimensions;
- decorative elements and composition;
- style period/influences/descriptors.

Repeated structures use stable semantic IDs. Array position is never identity.

### Explicit v1.0 -> v1.1 compatibility

`upgrade_design_revision_v1_to_v1_1()` performs an explicit additive conversion.
It preserves existing IDs, revision lineage and existing Product State values and
does not populate any new field.

Historical v1.0.0 artifacts are not rewritten or silently reinterpreted.

### Version-aware Product State traversal

A shared traversal projects both v1.0.0 and v1.1.0 revisions into:

- Knowledge Runtime State;
- Prompt Compiler specification/disclosures.

For an unchanged v1.0 revision, existing field ordering remains unchanged.
Upgrading that same revision to v1.1 without setting any new fields preserves the
rendered prompt text and specification entries.

### Knowledge target grammar v1.1

The frozen P0-16 target registry is implemented as 148 allowed Product State target
families with deterministic normalization for stable repeated identities:

- `side_stones.{group_id}`;
- `metal.components[].*` -> concrete stable component ID;
- `decorative_elements[].*` -> concrete stable element ID.

This module is additive. It does **not** modify Knowledge Library Contract v1.0.0,
its compiler hashes, durable storage, production validation evidence, or ACTIVE
release format.

### Reference Binding v1.0.0

The frozen Reference Binding JSON contract now has immutable Pydantic runtime models
covering reference role, feature-level `KEEP / CHANGE / LOCKED / INSPIRATION /
UNKNOWN`, provenance, observability, confidence, and presentation bindings.

Reference Binding remains external to Product State and does not mutate a design by
itself.

### Visualization Verification v1.0.0

The frozen verification contract now has immutable runtime models covering:

- PASS / FAIL / UNVERIFIABLE / NOT_APPLICABLE;
- BLOCKER / MAJOR / MINOR;
- ACCEPT / RETRY / ASK / CAD_3D_FALLBACK / DO_NOT_CLAIM;
- the twelve P0-12 verification dimensions;
- per-check evidence/error IDs and generation/design lineage.

Verification remains evidence about generated media, not Product State or
manufacturing truth.

## Deliberately unchanged

P0-17 does not:

- change `SCHEMA_VERSION = 1.0.0` for the historical v1 contract;
- mutate existing API/persistence database rows to v1.1;
- change Knowledge Library v1.0.0 compiler or durable artifact hashes;
- promote a new Knowledge runtime to ACTIVE;
- activate a production catalog for the 118 new fields;
- interpret Reference Binding as Product State automatically;
- invoke image providers or verification models.

## Next implementation boundary

The remaining work after P0-17 is runtime adoption:

1. persistence/API support for explicit DesignRevision v1.1 sessions;
2. Parser/Question/Rules coverage for selected new fields;
3. a versioned Knowledge Library v1.1 bundle/compiler/promotion path when curated
   policies for new targets exist;
4. persistence/linkage of Reference Binding and Verification records;
5. preproduction migration and representative end-to-end validation.

Those are integration/release tasks, not missing content in Knowledge Library v1.
