# P0-15 Canonical Target Classification & Runtime Schema vNext

Status: **WORKING — classification complete with source-recovery gate**  
Date: **2026-10-25**

## Executive result

P0-15 classifies the frozen P0 content baseline into runtime owners before any schema expansion. The
baseline remains **166 target/path families**, but this does **not** mean 166 Product State fields.

Current classification:

- Current Product State v1: **30**
- Candidate Product State vNext: **118**
- Interpretation metadata: **5**
- Reference Binding: **1**
- AI Generation State: **3**
- Output Profile: **4**
- Verification Result: **4**
- Derived runtime metadata: **1**

The key architectural result is that P0-11 and P0-12 do not enlarge Product State. Reference
semantics become a dedicated Reference Binding contract; verification/error knowledge becomes a
separate Visualization Verification Result contract. Presentation parameters remain in AI Generation
State / Output Profile.

## Current-runtime anchor

The current merged V2 design schema and Knowledge Library v1.0.0 remain the implementation source of
truth for existing Product State fields and policy targets. This step does not reinterpret those
contracts and does not activate a new knowledge release.

The existing Knowledge Library contract allows 30 policy target families. P0-14 already records that
the 166 content-governed target/path families are broader than the implemented runtime boundary.

## Schema vNext proposal

The proposed Jewelry Design Schema version is **1.1.0**, as an additive minor release rather than a
major rewrite.

Existing v1.0.0 snapshots remain immutable historical artifacts. New semantics are grouped into
nested models rather than exposed as 118 unrelated top-level fields:

1. Stone semantic extensions — variety/type, material-origin status, geographic origin,
   treatment status/list, cut-style class.
2. Side-stone population extensions — role, arrangement, location, coverage, total carat weight,
   sieve system/designation/range.
3. Prong configuration.
4. Halo state.
5. Pavé state.
6. Metal extensions — alloy system, coating, surface treatment and mixed/component metals.
7. Product-specific construction for ring, earrings, pendant, necklace, bracelet and brooch.
8. Product/whole-jewelry dimensions.
9. Style/design semantics — period/influences/descriptors, decorative elements and composition.

## Interpretation boundary

Creative intent is not treated as objective physical Product State truth. The current classification
keeps:

- `creative_intent`;
- `creative_intent_raw`;
- `creative_intent_descriptors`;
- `creative_intent_axes`;
- `proportions.scale_anchor`

in interpretation metadata.

This preserves the original user wording and normalized intent without pretending that a subjective
instruction is a measurable product fact.

## Reference Binding boundary

P0-11 Reference Semantics becomes a separate binding object linked to an existing Asset by
`asset_id`.

The draft contract supports:

- reference roles such as base design, feature donor, style inspiration, existing-product constraint,
  proportion reference and presentation reference;
- feature-level `KEEP / CHANGE / LOCKED / INSPIRATION / UNKNOWN`;
- explicit provenance and observability;
- presentation bindings routed separately from Product State.

The binding does not mutate Product State by itself.

## Visualization Verification boundary

P0-12 becomes a separate result contract for generated media.

The draft preserves:

- `PASS / FAIL / UNVERIFIABLE / NOT_APPLICABLE`;
- `BLOCKER / MAJOR / MINOR`;
- per-check evidence and optional confidence;
- error IDs;
- actions `ACCEPT / RETRY / ASK / CAD_3D_FALLBACK / DO_NOT_CLAIM`;
- the 12 P0-12 verification dimensions.

Verification results describe generated-media evidence. They are not jewelry properties.

## Source-recovery gate

The 166-row accounting is complete, but a normative schema freeze is intentionally blocked.

The original 56-target Matrix artifact and the individual P0-1 through P0-9 JSON/MD artifacts are not
present in the current workspace. Exact paths explicitly stated in the prior-chat completion record
are kept as exact; reconstructed target IDs are explicitly marked in the machine-readable map.

Before a normative Schema 1.1.0 contract is published:

1. reconcile the reconstructed original-Matrix IDs with the original Matrix artifact;
2. reconcile P0-1 through P0-9 reconstructed paths with their source artifacts, especially the
   exact P0-9 31-path register;
3. review the proposed Product State vNext field ownership;
4. then implement versioned schema/compiler migrations and executable regressions.

This is a source-traceability gate, not a content-completeness failure.

## Artifacts

- `data/knowledge/v1/p0-15-canonical-target-map-0.1.0.json`
- `specs/jewelry-design-schema/vnext-proposal-0.1.0.json`
- `specs/reference-bindings/v1-draft.schema.json`
- `specs/visualization-verification/v1-draft.schema.json`

## Non-goals

- no ACTIVE knowledge promotion;
- no existing schema mutation;
- no automatic migration of historical revisions;
- no provider or image-generation behavior change;
- no verification result stored as Product State;
- no silent inference of dimensions, materials, treatments or manufacturing facts.
