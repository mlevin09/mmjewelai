# P0-21 Knowledge Library v1.1 Runtime & Activation

Status: **IMPLEMENTED — CI PENDING**  
Date: **2026-10-25**

## Purpose

P0-21 creates a versioned Knowledge Library runtime path for the Product State
ownership frozen in P0-16 and implemented through P0-20.

The v1.0 contract remains immutable. P0-21 does not widen its target grammar,
change its compiled hashes, or reinterpret historical releases.

## Contract v1.1

Knowledge Library Contract v1.1 preserves the v1 evidence model:

Source → Claim → Domain Knowledge → Language Mapping → JewelAI Policy → Compiled Runtime.

The substantive contract change is the policy target grammar. v1.1 accepts the
frozen Jewelry Design Schema v1.1 Product State registry, including stable
collection templates for:

- side-stone groups via {group_id};
- metal components via {component_id};
- decorative elements via {element_id}.

Unknown targets remain fail-closed.

## Deterministic compiler

The v1.1 compiler:

- validates source/claim/concept/mapping/policy IDs and references;
- rejects COMPILED/ACTIVE lifecycle values in source bundles;
- preserves REVIEWED-only production compilation;
- validates language collisions using the same v1 semantics;
- accepts only policy targets in the frozen v1.1 target registry;
- emits immutable COMPILED runtime and manifest;
- computes deterministic canonical JSON and SHA-256 identity;
- never emits ACTIVE records.

## Policy runtime

The shared KnowledgePolicyEngine now accepts either compiled Contract v1.0 or
compiled Contract v1.1.

Template matching is generalized for group/component/element stable IDs. Existing
v1.0 state precedence, preservation, lock and source-lineage rules remain unchanged.

Design Schema v1.1 Product State can therefore be projected into a v1.1 Knowledge
runtime without changing the authoritative Product State model.

## Durable storage

KnowledgeArtifactStoreV1_1 provides immutable content-verified storage for v1.1
source/runtime/manifest/checksum artifacts.

Publishing the same package/version is idempotent only for byte-identical canonical
content. Loading recompiles and revalidates the source bundle and compares runtime,
manifest, checksums and release identity fail-closed.

## Production validation and activation

P0-21 adds a separate ProductionValidationReportV1_1 and
ActiveKnowledgeRuntimeV1_1.

The required production checks remain:

- compiler_contract;
- provenance_integrity;
- language_matcher;
- runtime_policy;
- prompt_enrichment_integration;
- behavioral_regression.

Every required check must PASS. EXPECTED_GAP remains non-passing for activation.

Promotion creates an immutable ACTIVE envelope around the exact compiled runtime;
the compiler-owned runtime itself remains active_for_production=false.

## Release qualification

qualify_knowledge_release_v1_1 performs a read-only qualification of an explicitly
selected v1.1 release using its durable store, ACTIVE envelope and production
validation report.

Qualification does not publish, promote, select, deploy or mutate the release.

## Compatibility

- Knowledge Library v1.0 remains unchanged and independently loadable.
- Jewelry Design Schema v1.0 and v1.1 remain versioned independently.
- P0-20 Prompt Enrichment compatibility is not reopened.
- v1.1 policy targets do not become Product State values automatically.
- content availability never overrides explicit/confirmed/locked user state.

## Deliberate non-goals

P0-21 does not:

- declare a real v1.1 JewelAI knowledge package ACTIVE;
- migrate the existing v1.0 production-intended catalog automatically;
- make v1.1 the default Knowledge release;
- deploy to preproduction or production;
- add new jewelry-domain content beyond the frozen P0 content baseline;
- weaken provenance or production validation gates.

## Exit gate

P0-21 is complete when:

1. a v1.1-only policy target compiles while the v1.0 contract remains unchanged;
2. the shared policy runtime projects Schema v1.1 state and matches v1.1 policies;
3. complete PASS evidence can create an exact v1.1 ACTIVE envelope;
4. durable v1.1 storage round-trips and revalidates deterministic artifacts;
5. v1.1 qualification verifies the selected durable runtime;
6. unknown v1.1 policy targets fail closed;
7. full Domain / Runtime API / Parser / Prompts / Knowledge / Ruff / Web CI is green.

After this gate, the Knowledge Library workstream in this chat is closed. Further
catalog population, preproduction activation and release rollout belong to a
separate development/release workstream.
