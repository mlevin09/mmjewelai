# ADR 0030: Parametric Knowledge as non-authoritative Prompt Enrichment references

Status: **Accepted**  
Date: **2026-10-24**

## Context

JewelAI now has two distinct reviewed knowledge artifacts:

- the semantic Production Jewelry Catalog under the Knowledge Library contract;
- the source-backed Parametric Gemstone Knowledge Base for quantitative size, weight, and
  material-density references.

The current Jewelry Design Schema represents authoritative center-stone dimensions as complete
length × width × depth values. Most calibrated gemstone tables provide only diameter or
length × width, and the Knowledge Library contract explicitly forbids treating carat weight as a
unique physical dimension.

Prompt generation still benefits from these source-backed quantitative references when the user has
specified material, shape, and carat weight but has not supplied exact dimensions.

## Decision

The Parametric Gemstone Knowledge Base remains a separate versioned runtime artifact and is not
merged into semantic Product State or the semantic Knowledge Library runtime.

Prompt Enrichment may attach a parametric reference only when all of the following are true:

1. center-stone material is authoritative;
2. center-stone shape is authoritative;
3. center-stone carat weight is authoritative;
4. the catalog contains an exact material + shape + weight record;
5. the record is REVIEWED;
6. authoritative dimensions are not already present.

Selection is deterministic and does not interpolate, extrapolate, round, or infer a nearest weight.

When multiple reviewed sources provide the same selected geometry, the runtime deduplicates that
geometry while preserving every source ID and record ID. General calibrated references are preferred
over specialized standard-proportion references when both exist for the same context.

The selected references are stored in the immutable `PromptEnrichmentResult` together with the exact
parametric catalog ID, artifact version, and catalog SHA-256. Corrections and later cycles fail closed
if that catalog lineage changes.

The provider-neutral Internal Final Prompt renders selected values only inside an explicit
`PARAMETRIC REFERENCES (NON-AUTHORITATIVE)` section. These values:

- are not authoritative design facts;
- are not constraints or preservation requirements;
- do not satisfy a missing Product State dimension by themselves;
- do not overwrite explicit, confirmed, or locked user state;
- preserve source and uncertainty text.

Authoritative dimensions and explicit `NotApplicable` dimensions suppress parametric references.
For material, shape, and weight, an explicit user value is authoritative even before a separate
confirmation action. Derived or assumed values qualify only after confirmation; unaccepted
recommendations and unconfirmed assumptions never provide selection context. The same eligibility
check is enforced when references enter Prompt Enrichment so a caller cannot reintroduce guidance
that deterministic selection correctly suppressed.

The Rules Engine quantitative fact match context also includes stone shape, preventing a fact for one
shape from being reused for another shape with the same material and carat weight.

## Versioning consequence

The Prompt Enrichment result contract advances to **1.2.0** because it gains additive structured
parametric lineage and reference fields.

The Internal Final Prompt schema remains **1.1.0**. Its structured schema does not gain new
parametric fields; the already-hashed enrichment result provides lineage, while the rendered prompt
contains the clearly labeled reference section.

## Alternatives considered

### Derive Product State dimensions directly from calibrated tables

Rejected. Most source rows do not provide full length × width × depth, and calibrated dimensions are
estimates rather than measurements of the user's actual stone.

### Interpolate between nearby carat weights

Rejected for v1. Interpolation would create a new quantitative inference model requiring its own
validation, uncertainty policy, and provenance.

### Merge parametric records into the semantic Knowledge Library

Rejected. Semantic terminology/policy and quantitative reference facts have different contracts,
risk profiles, and update cadences.

## Consequences

- Prompt generation can use real quantitative jewelry references without presenting them as measured
  facts.
- Restart/correction behavior stays deterministic because the catalog identity and hash are persisted.
- Product State remains the authority for accepted dimensions.
- Future derivation of complete dimensions, interpolation, or manufacturing tolerances requires a
  separate explicit contract and validation step.
