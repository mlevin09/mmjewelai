# Parametric Gemstone Knowledge Base v1.0.0

Status: **REVIEWED production-intended quantitative catalog**.

This boundary stores sourced quantitative gemstone reference data separately from the semantic
Knowledge Library. The canonical artifact is
`data/knowledge-base/v1.0.0.json` with catalog ID
`jewelai.production.parametric_gemstones`.

## Purpose

The catalog supplies machine-readable reference facts for:

- specific gravity by gemstone material;
- calibrated size ↔ carat reference points;
- round diameter references;
- fancy-shape length × width references;
- selected standard-proportion references with depth where the source provides it.

The catalog is explicitly **reference knowledge**, not measurement authority. Carat is mass, not
physical size. Equal weight can produce different dimensions because shape, proportions, depth,
girdle and material density vary.

## Contract

The normative schema is [schema.json](schema.json). Every quantitative record includes:

- stable record ID;
- canonical material and shape IDs;
- units encoded by the field contract (ct and mm);
- source ID;
- applicability;
- uncertainty;
- review status.

Sources preserve URI, evidence tier, version/access marker and retrieval date.

## Current v1 coverage

The v1 artifact contains:

- 12 reviewed sources;
- 8 source-backed specific-gravity records;
- 564 calibrated size/weight reference records;
- round, oval, pear, emerald-cut/octagonal and marquise calibrated series across common gemstone
  materials;
- independent one-carat diamond references from GemSelect, Stuller and OctoNus, including the
  OctoNus Tolkowsky standard-proportion reference.

One ambiguous source datum in the public zircon octagon table is deliberately omitted rather than
silently corrected.

## Safety invariants

- A carat-weight value never determines a unique dimension.
- Calibrated entries cannot claim exact measured dimensions.
- A specific-gravity fact is never itself a size-conversion rule.
- Approximate tables retain source-specific applicability and uncertainty.
- No interpolation, extrapolation or nearest-neighbor inference exists in this v1 contract.
- No manufacturing tolerance is invented.
- Product State remains authoritative; this catalog is evidence for later deterministic enrichment.

## Relationship to Prompt Enrichment and the semantic Knowledge Library

The semantic Knowledge Library owns terminology, concepts and product policy. This quantitative
catalog owns sourced numeric references.

Prompt Enrichment now loads this catalog as a separately version-pinned runtime artifact. It may
select only exact material + shape + carat matches and carries the catalog ID, artifact version,
SHA-256, record IDs, source IDs, applicability, and uncertainty into the immutable enrichment result.
No interpolation or nearest-weight lookup is performed.

Selected values are rendered only as **non-authoritative parametric references**. They do not mutate
Product State, do not satisfy missing authoritative dimensions, and disappear when authoritative
dimensions already exist. See [ADR 0030](../../docs/adr/0030-parametric-knowledge-prompt-enrichment-references.md).

## Verification

From the repository root:

```sh
python -m pip install -e './packages/domain[test]'
python -m pytest -c packages/domain/pyproject.toml packages/domain/tests/test_knowledge_base.py -q
python -m pytest -c packages/domain/pyproject.toml packages/domain/tests -q
python -m ruff check packages/domain
python -m ruff format --check packages/domain
```
