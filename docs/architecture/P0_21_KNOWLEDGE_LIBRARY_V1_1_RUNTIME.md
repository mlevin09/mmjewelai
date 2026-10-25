# P0-21 Knowledge Library v1.1 Runtime & Activation

Status: **IMPLEMENTED ON FEATURE BRANCH — CI GATED**  
Date: **2026-10-25**

## Purpose

P0-21 closes the final engineering step in this chat by providing a separate Knowledge Library
runtime for Jewelry Design Schema v1.1 while preserving the existing Contract v1.0 lineage.

This is runtime capability, not a claim that a complete 148-target production catalog has been
reviewed and activated.

## Version isolation

Contract v1.0.0 remains unchanged.

Contract v1.1.0 is implemented in separate modules for compiler, policy runtime, durable storage and
activation. The v1.1 compiler accepts the frozen Product State target grammar established by P0-16
and implemented by P0-17.

The compiler does not accept Reference Binding, presentation, verification or other non-Product-State
targets.

## Compiler

The v1.1 source model preserves the evidence layers used by v1.0:

Source -> Claim -> Domain Knowledge -> Language Mapping -> JewelAI Policy.

It additionally accepts stable collection templates for the expanded schema:

- side-stone group targets;
- metal component targets;
- decorative-element targets.

Compilation remains deterministic and emits a canonical runtime plus manifest. Runtime SHA-256 is
derived from canonical UTF-8 JSON.

Only REVIEWED source records participate in the compiled runtime. Reviewed dependencies on
non-reviewed evidence remain fail-closed.

## Policy runtime

The v1.1 policy engine projects the version-aware Product State traversal into Knowledge Runtime
State and applies the existing generic authority rules:

- explicit/confirmed state precedence;
- KEEP;
- LOCKED;
- lower-precedence rejection;
- knowledge-source lineage validation.

It resolves stable policy templates against concrete component/group/element IDs without treating
array position as identity.

## Durable storage

KnowledgeArtifactStoreV1_1 publishes immutable source/runtime/manifest/checksum artifacts and verifies
them on every load.

Publishing the same package/version is idempotent only for byte-identical canonical artifacts.
Different content under the same immutable identity is rejected.

The v1.0 durable store is not modified.

## Production validation and activation

ProductionValidationReportV1_1 requires the same complete validation dimensions used by the existing
Knowledge release gate:

1. compiler contract;
2. provenance integrity;
3. language matcher;
4. runtime policy;
5. Prompt Enrichment integration;
6. behavioral regression.

Every required check must PASS.

The ACTIVE envelope is separate from the compiler-owned runtime. Promotion does not mutate compiled
content.

P0-21 does **not** publish an ACTIVE production v1.1 release and does not change current production
selection.

## Prompt Enrichment

Dedicated v1.1 enrichment entry points can consume a compiled or durably verified ACTIVE v1.1
runtime and produce the existing provider-neutral enrichment result/compiled prompt structure.

This allows reviewed policies for additive Product State targets such as composition or treatment
semantics to participate in runtime behavior without changing the legacy v1.0 enrichment entry point.

## Regression gates

P0-21 adds coverage for:

- acceptance of valid Schema v1.1 Product State targets;
- stable collection templates `{group_id}`, `{component_id}`, `{element_id}`;
- rejection of Reference Binding / Verification / presentation targets;
- deterministic compile + manifest hash;
- v1.1 Product State projection into the policy runtime;
- immutable durable publish/load;
- exact ACTIVE evidence verification;
- EXPECTED_GAP blocking activation;
- explicit separation from Contract v1.0;
- Prompt Enrichment using a v1.1 Knowledge runtime.

## Non-goals

- no fabricated policies for all 148 targets;
- no automatic ACTIVE promotion;
- no production or preproduction release switch;
- no change to Knowledge Library v1.0 hashes;
- no movement of Reference Binding or Verification data into Product State;
- no new product-domain content.

## Completion meaning

After P0-21, the Knowledge Library content baseline is complete for the frozen v1 scope and the
runtime architecture is capable of versioned use with Schema v1.1.

Operational catalog expansion remains an incremental governance activity rather than a prerequisite
for declaring the v1 content baseline ready for use.
