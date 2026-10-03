# Knowledge Library Contract v1.0.0

Status: **FROZEN architecture contract**.  
Architecture confirmation: **CONFIRMED_WITH_DEFERRALS**.  
Production activation: **false**.

This contract freezes the JewelAI Knowledge Library boundary validated through the solitaire vertical
slice and the three-stone architecture stress test. It is the implementation target for the production
compiler and validator. It does not publish a production knowledge catalog and does not promote any
record or rule to ACTIVE.

## Canonical chain

```text
SOURCE → CLAIM → DOMAIN KNOWLEDGE → LANGUAGE → JEWELAI POLICY → COMPILED RUNTIME → TEST
```

The layers have separate responsibilities:

- **Source** records evidence provenance and evidence class.
- **Claim** records an evidence-backed assertion and points to one primary Source; additional
  corroborative sources are explicit.
- **Domain Knowledge** records language-neutral jewelry concepts and relationships backed by Claims,
  except explicitly marked structural-schema nodes.
- **Language** maps RU/EN surface forms to canonical concept IDs without changing domain meaning.
- **JewelAI Policy** records product behavior separately from external/domain truth.
- **Compiled Runtime** is deterministic output derived from pinned input artifact versions.
- **Test** verifies integrity, contract behavior and semantic behavior. EXPECTED_GAP is never PASS.

Provider-specific prompt syntax is outside this contract.

## Stable IDs and references

Canonical concept IDs are language-neutral and stable. Display wording is never an identifier.
References fail closed: a compiler must reject unresolved Source, Claim, concept, parent, relationship
or policy-target references required by the pinned package.

Published IDs are not silently reassigned. A semantic replacement uses a new ID plus explicit
deprecation/replacement metadata in the owning artifact.

## Lifecycle

Allowed lifecycle states are:

`DRAFT`, `REVIEWED`, `COMPILED`, `ACTIVE`, `DEPRECATED`, `REJECTED`.

The compiler may emit COMPILED records from eligible REVIEWED inputs. It must not emit ACTIVE.
ACTIVE is a later production-promotion decision. REVIEWED means internal curation, not automatic team
or production approval.

## Language contract

RU and EN maturity are independent. A language mapping uses one of:

- `DIRECT`
- `CONTEXTUAL`
- `INPUT_ONLY`
- `AMBIGUOUS`

Mapping quality uses one of:

- `EXACT`
- `PREFERRED`
- `CONTEXT_DEPENDENT`
- `APPROXIMATE`
- `NO_DIRECT_EQUIVALENT`

An AMBIGUOUS surface form cannot simultaneously be an unconditional DIRECT normalization for the
same locale and scope. The compiler must reject exact direct/ambiguity collisions.

## Product-state semantics

Knowledge enrichment must preserve the distinction between:

`EXPLICIT`, `NORMALIZED`, `MISSING`, `AMBIGUOUS`, `RECOMMENDED`, `ACCEPTED`,
`ASSUMED`, `NOT_APPLICABLE`, `CONFIRMED`, and `LOCKED`.

MISSING is not NOT_APPLICABLE. RECOMMENDED is not ACCEPTED. ASSUMED is not CONFIRMED.
Preservation intent is `CHANGE`, `KEEP`, or `LOCKED`.

When multiple candidate values compete, provenance precedence is:

1. `USER_CONFIRMED`
2. `USER_EXPLICIT_LATEST`
3. `USER_ACCEPTED_RECOMMENDATION`
4. `NORMALIZED_FROM_USER`
5. `KNOWLEDGE_INFERRED`
6. `JEWELAI_RECOMMENDED`
7. `VISUALIZATION_ASSUMPTION`

A lower-precedence source cannot silently overwrite a higher-precedence value.

## Parameter targets and collections

Scalar targets use canonical dotted paths such as `center_stone.shape` and `metal.color`.

Repeated components use a stable collection key, never an array index. The v1 template token is
`{group_id}`. The required additive refinement from the architecture stress test is frozen as:

```text
side_stones.{group_id}.stones.material
side_stones.{group_id}.stones.shape
side_stones.{group_id}.stones.cut
side_stones.{group_id}.stones.weight
side_stones.{group_id}.stones.dimensions
side_stones.{group_id}.stones.color
side_stones.{group_id}.stones.setting
side_stones.{group_id}.stones.orientation
side_stones.{group_id}.quantity
```

These templates align with Jewelry Design Schema v1.0.0, whose side-stone groups use stable
`group_id` values. Runtime expansion must bind a template only to an existing concrete group ID.
The Knowledge Library must not create a group as a side effect of normalization or policy evaluation.

## Semantic invariants frozen from validation

The compiler/runtime must preserve at least these invariants:

- engagement occasion/purpose is not solitaire style;
- prong setting type and prong count are separate;
- generic bezel and bezel coverage are separate; RU `глухая закрепка` is not an unconditional EXACT
  mapping to generic bezel;
- rose gold and red gold are distinct canonical colors;
- white gold does not imply rhodium coating;
- cushion shape and cutting style are separate;
- round shape does not imply round brilliant;
- carat weight is mass and does not determine physical dimensions;
- center-stone role does not imply diamond, largest stone, or any material;
- qualitative shank width has no universal invented millimetre thresholds.

## Compiler gate

Compilation fails closed on:

- broken canonical references;
- unresolved required parent or relationship references;
- broken Domain Knowledge → Claim → Source provenance;
- Language mappings pointing to unknown concepts;
- policy targets outside the allowed target grammar or unavailable schema scope;
- unexpected DRAFT promotion;
- exact DIRECT/AMBIGUOUS collisions;
- duplicate semantic IDs or conflicting same-scope aliases;
- rules without valid source/provenance;
- schema-version mismatch.

Successful compilation may produce COMPILED runtime artifacts only. It must set
`active_for_production=false` until the later ACTIVE promotion gate.

## Validation outcomes

Test outcomes are exactly `PASS`, `EXPECTED_GAP`, or `FAIL`.
EXPECTED_GAP represents an intentionally isolated unsupported/ambiguous case and never contributes to
the PASS count. An unresolved FAIL or HIGH architectural defect blocks the relevant gate.

## Relationship to existing V2 contracts

This contract complements rather than replaces:

- Jewelry Design Schema v1.0.0 for canonical design state, provenance, confirmation and locks;
- Domain Dictionary v1.0.0 for deterministic terminology normalization;
- Rules Engine v1.0.0 for deterministic ask/derive/assume/block/ready policy;
- the Limited Knowledge Base boundary for sourced quantitative facts.

The Knowledge Library may compile into those boundaries, but cannot bypass them. Prompts and model
outputs remain untrusted proposals and cannot define business rules or overwrite locked fields.

## Accepted deferrals

The following do not block Contract v1.0.0:

1. Production Rules v1 currently expands `side_stones[*].quantity`; generalized repeated-field
   runtime targeting is deferred to production integration.
2. Multi-focal designs without a unique center are outside the confirmed solitaire + three-stone
   architecture slice and require a future explicit schema/domain decision.
3. Corroborative-only evidence must be represented explicitly (for example with
   `supporting_source_ids`) rather than masquerading as an unused primary source.

Production parser/matcher, RU morphology and phrase boundaries, production ambiguity/context
resolution, Matrix Engine integration, and production behavioral regression remain implementation
work. Contract freeze does not claim those capabilities exist.

## Versioning

Contract version is `1.0.0`. Incompatible changes to record meaning, target grammar, lifecycle
semantics or compilation rules require a new major version. Additive fields require a minor version.
Documentation-only corrections may use a patch version. Historical compiled packages pin the exact
contract and input artifact versions and are never silently migrated.

The machine-readable normative manifest is
[contract-v1.0.0.json](contract-v1.0.0.json), and record-shape validation is defined by
[schema.json](schema.json).
