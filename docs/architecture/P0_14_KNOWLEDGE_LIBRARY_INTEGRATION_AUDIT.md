# P0-14 Knowledge Library canonical integration audit

Status: **EXECUTED - PARTIAL_BY_SCHEMA**  
Date: **2026-10-25**  
Scope: canonical-library integration and runtime validation after P0-13 content closure.

## Result

P0-13 closes the content baseline, but it does not imply that the current V2 runtime represents every
content-governed target. The current repository has a mature Knowledge Library v1.0.0 runtime boundary,
Prompt Enrichment integration, durable release lineage and production validation gate. That runtime is
real and should be preserved.

The P0 content baseline is broader than the current runtime contract:

- P0-13 records **166 content-governed target paths/families**.
- Knowledge Library v1.0.0 currently allows **21 scalar + 9 collection = 30 policy target families**.
- Jewelry Design Schema v1.0.0 stores the current canonical Product State under jewelry type, metal,
  center stone, side-stone groups, construction, style, references and visual constraints.
- Therefore full P0 content cannot be compiled into the current Product State / Knowledge Library
  target grammar without a versioned schema change.

This is not a content failure. It is the expected transition from content closure to runtime contract
evolution.

## What is already integrated

### Semantic catalog core

The production-intended catalog at `data/knowledge/v1/jewelry-core-1.0.0.json` already covers the
current schema boundary: jewelry types, metals, gemstone materials, stone shapes/cuts/settings,
orientation, general color, style, selected construction concepts, RU/EN language mappings and
product policies.

### Parametric knowledge

ADR 0030 already integrates parametric gemstone references into Prompt Enrichment as a separate,
non-authoritative layer. It correctly avoids turning estimated size references into measured Product
State facts.

### Prompt Enrichment lineage

The controlled Prompt Enrichment path already pins exact knowledge-release identity and fails closed
when durable release lineage no longer matches. This foundation should be extended rather than
replaced.

## P0-10 integration result

P0-10 is only partially representable in current Product State.

The current single `style` field can carry selected canonical style IDs, but P0-10 intentionally
separates:

- structural style;
- historical period or movement;
- descriptive aesthetic;
- decorative technique;
- motif;
- composition;
- creative intent.

Collapsing those layers into one `style` tuple would destroy semantics and contradict the P0-10
guardrails. A versioned additive Design Schema decision is required before those layers become
authoritative runtime fields.

## P0-11 integration result

Terminology normalization can extend the existing Knowledge Library language layer when the target
canonical concept already exists.

Reference semantics cannot be represented fully today. `AssetReference` currently records only
`design/material/style/proportion` purpose. P0-11 requires feature-level semantics including
`KEEP / CHANGE / LOCKED / INSPIRATION / UNKNOWN`, conflict handling and observability boundaries.
Those are not equivalent to the current four-purpose enum and must not be silently encoded into
free-text notes.

## P0-12 integration result

P0-12 must not be forced into Product State.

Its PASS / FAIL / UNVERIFIABLE / NOT_APPLICABLE status, severity, evidence, actions and error taxonomy
describe verification results about generated media. They belong to a separate versioned
visualization-verification result contract linked to Product State / generation lineage.

This preserves the existing project distinction between Product State and AI Generation State.

## Executable regression gate added in this slice

The branch adds a machine-readable coverage manifest and a deterministic domain test that:

1. records the P0-13 166-target content baseline separately from the 30 current Knowledge Library
   target families;
2. refuses to label current runtime coverage as complete;
3. proves that an unversioned P0-10 target such as `composition.symmetry` is rejected by the current
   fail-closed compiler.

The test is deliberately a boundary test, not a workaround. The correct next change is a reviewed
versioned schema/contract slice, not weakening validation.

## Next versioned engineering slices

1. Recover/consolidate P0-1 through P0-12 source artifacts into a canonical source package.
2. Build a complete target-classification map:
   - current Product State;
   - additive Product State;
   - interpretation metadata;
   - reference-binding metadata;
   - verification state;
   - intentionally non-runtime knowledge.
3. Version Jewelry Design Schema for approved additive Product State fields.
4. Version Knowledge Library target grammar accordingly.
5. Add feature-level reference-binding contract.
6. Add separate visualization-verification result contract.
7. Convert semantic mini-tests/closure tests into executable regressions.
8. Only after those gates pass, qualify an exact compiled runtime for ACTIVE promotion.

## Non-goals

- no ACTIVE promotion;
- no weakening of the current fail-closed compiler;
- no invented migration of 166 content families into 30 existing targets;
- no claim that provider/model verification is complete;
- no manufacturing/CAD truth inferred from visualization content.
