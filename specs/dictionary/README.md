# Domain Dictionary v1 — implementation brief

Create versioned stable IDs and definitions for materials, shapes/cuts, settings, metal colors/purities, construction and styles.
Entries contain category, canonical term, synonyms by locale, definition, provenance/review state and deprecation aliases.
Keep material emerald distinct from emerald cut. Ambiguous synonyms return an ambiguity result rather than choosing silently.
Initial RU/EN terminology is a proposed starting scope subject to review.
Factual gemstone dimensions belong in the separate sourced knowledge base.

Deliver schema, seed data, normalization loader and tests for synonyms, ambiguity, duplicate IDs, cross-category conflicts, unsupported terms and deprecated aliases.
