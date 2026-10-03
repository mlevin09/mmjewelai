# ADR 0027: Freeze Knowledge Library Contract v1.0.0

Status: Accepted. Date: 2026-10-03.

## Context

JewelAI needs a bilingual, evidence-traceable Knowledge Library for Prompt Enrichment without letting
LLM output, retail wording or provider-specific prompt syntax become domain truth. The architecture
was exercised first with a solitaire engagement-ring slice, then with a three-stone stress case.

The validated chain is Source → Claim → Domain Knowledge → Language → JewelAI Policy → Compiled
Runtime → Test. Reference validation closed with no unresolved FAIL or HIGH architectural defect.
The three-stone stress case exposed one additive need: repeated side-stone parameters must be addressed
by stable group ID rather than array position.

Existing V2 contracts already separate canonical Design state, Dictionary normalization, Rules
decisions and sourced Knowledge Base facts. The Knowledge Library must complement those contracts,
not silently replace them.

## Decision

Freeze Knowledge Library Contract v1.0.0 under `specs/knowledge-library`.

The contract:

- keeps Source, Claim, Domain Knowledge, Language and JewelAI Policy as separate versioned layers;
- uses language-neutral canonical IDs while RU and EN mappings mature independently;
- preserves explicit lifecycle states and forbids compiler-driven ACTIVE promotion;
- requires fail-closed provenance and reference validation;
- distinguishes ambiguous/contextual/input-only language from direct normalization;
- preserves state, provenance precedence, confirmation and lock semantics;
- adds collection-scoped parameter templates using `{group_id}` for existing side-stone groups;
- preserves the validated no-silent-inference invariants;
- keeps provider-specific prompt syntax outside the library.

Architecture confirmation is `CONFIRMED_WITH_DEFERRALS`; production activation remains false.

## Alternatives

Keeping the solitaire-only flat runtime contract would fail to represent repeated side-stone
parameters safely. Introducing a generic entity graph would duplicate the stable side-stone group
identity already present in Jewelry Design Schema v1.0.0. Collapsing Source/Claim/Domain/Policy into a
single catalog would lose evidence and product-policy boundaries.

## Consequences

Step 9 can implement a deterministic production compiler and validator against a pinned contract.
Historical packages must pin exact contract and input artifact versions. Incompatible contract
semantics require a new major version.

The current Rules Engine does not yet provide generalized repeated-field runtime targeting, and
multi-focal designs without a unique center remain outside this confirmed slice. Those are explicit
deferrals, not implicit behavior.

No catalog or rule becomes ACTIVE by this ADR.

## Validation

Architecture confirmation gate: 10/10 criteria passed, with explicit non-blocking deferrals.
Reference compile integrity: 12/12 PASS.
Reference semantic corpus: 38 PASS, 6 EXPECTED_GAP, 0 FAIL.
Three-stone stress checks: 12/12 PASS after the collection-scoped refinement.

The normative contract is `specs/knowledge-library/contract-v1.0.0.json`; record shapes are defined
by `specs/knowledge-library/schema.json`; the confirmation record is
`docs/architecture/KNOWLEDGE_LIBRARY_ARCHITECTURE_CONFIRMATION.md`.
