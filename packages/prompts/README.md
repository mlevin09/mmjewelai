# JewelAI Prompt Compiler

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
Knowledge Library enrichment slice. `PromptEnrichmentResult` v1.1.0 retains the exact validated
proposal on every `EnrichmentDecision`, including kept and blocked proposals, so later persistence
can retain attempted value, source, provenance and preservation intent. The result remains derived
evidence: it does not mutate `DesignRevision`, accept recommendations automatically, create repeated
groups, interpret policy prose, or alter the backward-compatible `CompiledPrompt`.

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
cross-session evidence, release/artifact mismatches, altered enrichment hashes, or a `CompiledPrompt`
that no longer matches the same revision. It does not select a release or re-enrich.

The builder returns two versioned derived artifacts from the same snapshot:

- `UserReadableJewelryDescription` v1.0.0 renders deterministic EN/RU prose without schema paths,
  stable group IDs, UUIDs, hashes, or release metadata. Unknown or deferred facts remain explicit;
  values are never invented.
- `InternalFinalPrompt` v1.1.0 is the structured provider-neutral module handoff. It retains
  authoritative design facts, requirements, prohibitions, locks/preservation, accepted versus
  unaccepted enrichment evidence, unresolved details, decision lineage, release/artifact
  provenance, readiness, and a canonical SHA-256. Its deterministic text rendering is derived from
  that structure and contains no provider/model syntax. Versioned `FinalPromptConstraintEvidence`
  preserves explicit non-schema user constraints with exact message/span, revision/cycle lineage,
  active/superseded/unresolved status, and its own canonical hash. Only verified active evidence is
  rendered as authority; ambiguous evidence is never promoted into a requirement.

This new contract is intentionally distinct from `CompiledPrompt`; the existing compiler and live
API/generation path are unchanged. Step #13 will provide reviewed runtime integration. The builder
uses no network, provider, persistence, clock, random ID, or catalog fallback.

## Internal Final Prompt handoff v1.0.0

Step #14C adds `InternalFinalPromptHandoff` as a small downstream-facing envelope around the exact
validated `InternalFinalPrompt` v1.1.0. It binds the embedded prompt to organization/session,
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

```sh
python -m pip install -e './packages/domain[test]'
python -m pip install -e './packages/prompts[test]'
python -m jewelai_prompts.schema specs/prompts/schema.json
python -m jewelai_prompts.final_schema specs/prompts/internal-final-prompt-schema.json
python -m jewelai_prompts.handoff_schema specs/prompts/internal-final-prompt-handoff-schema.json
python -m pytest -c packages/prompts/pyproject.toml packages/prompts/tests -q
```
