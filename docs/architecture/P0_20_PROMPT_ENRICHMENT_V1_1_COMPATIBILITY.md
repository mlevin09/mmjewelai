# P0-20 Prompt Enrichment v1.1 Compatibility & Full Revision Transition Contract

Status: **IMPLEMENTED ON FEATURE BRANCH — CI GATED**  
Date: **2026-10-25**

## Purpose

P0-20 removes the controlled-adoption blocker introduced in P0-19 by making the
Prompt Enrichment consumer chain and the immutable Product State transition engine
safe for Jewelry Design Schema v1.1.0.

This step is compatibility work. It does not add new parser vocabulary, new jewelry
business rules, new Knowledge content, or provider behavior.

## Revision transition contract

The existing revision engine remains the single authoritative implementation for:

- edit;
- confirm;
- lock;
- unlock.

It now accepts both Design Revision v1.0.0 and v1.1.0 and emits the same schema
version as the current revision.

The transition traversal is extended to preserve v1.1 nested state, including:

- side-stone groups by stable `group_id`;
- metal components by stable `component_id`;
- decorative elements by stable `element_id`;
- nested state wrapped inside KnownValue containers such as composition,
  decorative-element collections and component collections.

Locked nested state cannot be changed, removed, renamed, or silently unlocked
through an ordinary edit.

## Prompt Enrichment compatibility

The following deterministic consumer stages now accept versioned revisions:

- parsed candidate enrichment;
- clarification planning/continuation;
- constraint-evidence assembly;
- parametric-reference selection;
- clarification answer processing;
- user-correction reenrichment;
- internal Prompt Enrichment runtime orchestration;
- final-prompt snapshot assembly.

The existing Question and Rules semantics remain unchanged. P0-20 only ensures that
the same approved semantics can operate on a v1.1 snapshot without downgrading or
dropping additive Product State.

## Parser contract

Prompt Enrichment consumes the versioned Parser Proposal union established in
P0-19. Parser Proposal v1.0.0 remains unchanged; v1.1 sessions carry
ParserProposalV1_1.

## Migration consequence

The P0-19 runtime blocker
`PROMPT_ENRICHMENT_RUNTIME_V1_1_UNSUPPORTED` is removed after this compatibility
slice because the configured Prompt Enrichment runtime can now preserve and process
v1.1 Product State through its existing workflows.

Migration remains explicit and compare-and-swap guarded. New sessions are not
silently migrated by this step.

## Regression coverage

P0-20 adds targeted regression coverage for:

1. nested v1.1 composition state through confirm/lock/edit transitions;
2. stable component-ID traversal for nested metal-component state;
3. a migrated v1.1 session entering the internal Prompt Enrichment runtime;
4. preservation of an additive v1.1 style descriptor while the existing parser
   changes supported legacy fields;
5. final-prompt assembly from the resulting v1.1 authoritative revision.

## Non-goals

- no new Knowledge Library release activation;
- no new product-domain questions or Rules;
- no automatic session migration;
- no provider/model invocation changes;
- no production/preproduction deployment;
- no claim that every additive v1.1 field has direct Parser/Question/Rules semantics.

## Exit gate

P0-20 is complete only when Domain, Runtime API, Parser, Prompts, Knowledge
regressions, API tests, Ruff and Web CI are green on the final PR head.
