# JewelAI Prompt Compiler

## B1: pure canonical generation preparation (not wired to application runtime)

Implementation record: [ADR 0032 (pending B1 review)](../../docs/adr/0032-canonical-generation-preparation-b1.md).

`project_revision()` extracts the legacy compiler's existing structured projection. It preserves
canonical targets/stable IDs, applicability, origin, confirmation, locks and disclosures without
compiling text. The legacy compiler reuses these helpers; historical schemas and serialized hashes
are unchanged.

`build_generation_preparation(source_handoff, gate_evidence, preparation_id=..., created_at=...)`
validates the staged `CanonicalInternalFinalPrompt`/handoff **2.0.0** and caller-supplied
`PreparationGateEvidence`. It returns a `GenerationPreparation` **1.0.0** owning immutable canonical
UTF-8 bytes. Its `.payload` / `.model_dump()` views are fresh defensive copies. IDs and timestamps
are explicit inputs, never generated. The wire schema is available from
`GenerationPreparationPayload.model_json_schema()` in `downstream_preparation`.

The successor source retains every original field plus typed parametric references/disclosures and
the bound user-readable description. The latter lets validation check the existing internal-text
formatter exactly, rejecting added untyped instructions without parsing prose. It is retained
internally, not sent to a provider or promoted to independent Product State authority. These types
are staged contracts only: `enrich_prompt()` and all current assembly/storage writers stay unchanged.

The semantic renderer uses typed facts/constraints only: requirements, active prohibitions, KEEP,
LOCKED, current accepted values, advisory reference context/uncertainty, disclosures and nonblocking
unresolved classifications. Recommendations and rejected/superseded instructions are retained in
source history, not promoted into requirements. Canonical facts must match the supplied revision;
missing mandatory meaning, inconsistent mappings and unrecognized executable instructions fail
closed with `unsupported_source_semantics`. Stable repeated-entity IDs become local sorted aliases
only in execution text; source and provenance remain unchanged. No internal envelope is forwarded.

Sorted compact JSON preserves exact Unicode/numbers, rejects duplicate keys/nonfinite values/
surrogates, and requires canonical byte round trips. New hashes are domain-separated for rendering,
gate, decision frontier and full artifact; existing source hashes retain their original algorithm.
Validation re-renders exact execution bytes/lengths/coverage instead of trusting hashes alone.

The **provisional**, non-production-qualified #118 bounds are 1 MiB source+gate, 2 MiB full artifact,
20,000 rendered Unicode code points / 80,000 UTF-8 bytes. No truncation, legacy fallback, or expansion
of legacy `Text`/`LongText` occurs. Image-bearing `references` fail explicitly: B1 has no reference
image transport/cutover policy. Some otherwise valid professional sources therefore cannot be
prepared yet; this is not full Schema v1.1 qualification.

Gate evidence validates supplied coherence/readiness, not membership, authenticity or a real ACTIVE
lookup. B2 must obtain the authoritative transaction-scoped revision/cycle/plan/decision frontier and
verified release bytes. B3/B4 must wire/qualify the sole canonical downstream path. This module does
not access a database, network, clock, provider, API or catalog activation. The persisted HTTP→worker
`no halo` P1 remains open; pure B1 test success is **not** downstream or preproduction verification.

## Existing compiler and enrichment

This package compiles one validated immutable `DesignRevision` and one explicit versioned prompt
template artifact into a deterministic provider-neutral `CompiledPrompt`. It depends only on
Pydantic and `packages/domain`; it has no API, persistence, parser, provider SDK, Model Gateway,
network, image generation, clock, UUID, or randomness dependency.

Compilation traverses canonical fields in fixed schema order, sorts side-stone groups by stable
`group_id`, omits absent/Unknown states, preserves exact typed values and `NotApplicable`, and never
invents defaults. Derived uncertainty, assumed rationale, and applicability reasons remain visible
as structured disclosures and prompt text. Every lock is derived from the same canonical entries
into a structured manifest and rendered under the template's locked-constraint label.

`validate_compiled_prompt` recompiles from the pinned revision/template and requires complete model
equality, detecting altered text, hashes, entries, disclosures, metadata, or lock manifests.

`enrich_prompt` is the deterministic provider-neutral orchestration entry point for the current
Knowledge Library enrichment slice. `StructuredPromptEnrichmentResult` v1.3.0 retains the validated
proposal on every `EnrichmentDecision`, including kept and blocked proposals, so later persistence
can retain attempted value, source, provenance and preservation intent. The result remains derived
evidence: it does not mutate `DesignRevision`, accept recommendations automatically, create repeated
groups, interpret policy prose, or invoke the historical `CompiledPrompt` compiler. Structured
revision entries, locks and disclosures come from `project_revision()`. The frozen
`PromptEnrichmentResult` v1.2.0 reader and its original hashes remain available through
`decode_prompt_enrichment_result()`, including nested correction/answer history.

Proposal semantic state and provenance must use the authority combinations defined by the domain
runtime. Knowledge-derived proposals must cite an identifier present in the exact selected compiled
runtime; message/candidate identifiers for user-origin proposals are not reinterpreted as Knowledge
Library IDs. Parametric references require explicit user material/shape/weight values or confirmed
derived/assumed values, and are rejected when dimensions are known or explicitly not applicable.

`enrich_prompt_with_active_release` is the production-pinning boundary for one in-memory enrichment
cycle. Its caller must explicitly name a package ID and artifact version and supply the existing
ACTIVE envelope and production-validation report. It delegates durable artifact and evidence checks
to `KnowledgeArtifactStore.load_active_runtime()`, uses only the verified stored runtime, and records
the validation-report SHA-256 in the immutable enrichment result. It never selects a latest release.
The original `enrich_prompt` remains available for backward-compatible offline and validation use;
it does not claim verified ACTIVE provenance. Session persistence and runtime API wiring remain out
of scope for this boundary.

`assemble_internal_final_prompt` is the offline Step #12 boundary. It consumes one explicit,
single-revision `FinalPromptSnapshot`: the immutable Product State, latest applicable enrichment
result, exact verified ACTIVE Knowledge release pin, artifact versions, existing Rules Engine
decision, and normalized clarification/correction lineage. It fails closed for stale revisions,
cross-session evidence, release/artifact mismatches, altered enrichment hashes, or a structured
projection that no longer matches the same revision. Historical compiled entries may be read but
are never recompiled or promoted into new authority. It does not select a release or re-enrich.

The builder returns two versioned derived artifacts from the same snapshot:

- `UserReadableJewelryDescription` v1.0.0 renders deterministic EN/RU prose without schema paths,
  stable group IDs, UUIDs, hashes, or release metadata. Unknown or deferred facts remain explicit;
  values are never invented.
- Current `CanonicalInternalFinalPrompt` v2.0.0 is the provider-neutral module handoff. It retains
  authoritative design facts, requirements, prohibitions, locks/preservation, accepted versus
  unaccepted enrichment evidence, unresolved details, decision lineage, release/artifact
  provenance, readiness, and a canonical SHA-256. Its deterministic text rendering is derived from
  that structure and contains no provider/model syntax. Versioned `FinalPromptConstraintEvidence`
  preserves explicit non-schema user constraints with exact message/span, revision/cycle lineage,
  active/superseded/unresolved status, and its own canonical hash. Only verified active evidence is
  rendered as authority; ambiguous evidence is never promoted into a requirement.

This contract is intentionally distinct from `CompiledPrompt`; old generation write routes remain
B3 cutover dependencies, not a canonical fallback. B2 preparation never dispatches work. The builder
uses no network, provider, persistence, clock, random ID, or catalog fallback.

## Historical handoff and current preparation

The frozen `InternalFinalPromptHandoff` v1.0.0 reads historical `InternalFinalPrompt` v1.1.0.
Current builders emit B1's `CanonicalInternalFinalPromptHandoff` v2.0.0, retaining the typed
references, disclosures and bound description. The envelope binds the prompt to organization/session,
authoritative Product State revision, latest enrichment cycle, exact Knowledge release and both
release hashes, prompt schema/hash, readiness, and its own canonical hash. Accepted decision
lineage, active constraints, supersession history, unresolved evidence, and unaccepted
recommendations remain inside the embedded prompt without translation or duplicated authority.

`ready_for_downstream_preparation` follows existing readiness semantics: `ready` and
`ready_with_unresolved` are eligible for a later provider-specific preparation step, while
`blocked` is not. This flag does not authorize generation. The application runtime can construct a
handoff only by restoring current organization-scoped durable state; repeated/restarted reads are
deterministic and do not persist another record. No route or current caller sends this handoff to a
provider, and legacy `CompiledPrompt` generation is unchanged.

B2 adds authorized transaction-scoped preparation retention, not worker integration. See
[the bounded B2 contract and route inventory](../../docs/architecture/CANONICAL_PREPARATION_B2.md).
Frozen schema files remain unchanged; `canonical-preparation-schema.json` separately describes
the current contracts and original enrichment reader.

```sh
python -m pip install -e './packages/domain[test]'
python -m pip install -e './packages/prompts[test]'
python -m jewelai_prompts.schema specs/prompts/schema.json
python -m jewelai_prompts.final_schema specs/prompts/internal-final-prompt-schema.json
python -m jewelai_prompts.handoff_schema specs/prompts/internal-final-prompt-handoff-schema.json
python -m jewelai_prompts.canonical_schema specs/prompts/canonical-preparation-schema.json
python -m pytest -c packages/prompts/pyproject.toml packages/prompts/tests -q
```
