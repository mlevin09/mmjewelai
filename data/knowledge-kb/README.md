# knowledge-kb

Seeds for Knowledge Library Contract 2.0 ([ADR 0048](../../docs/adr/0048-knowledge-library-kb-postgresql-contract-2.md)).
They are inputs to the `kb` drafts, not a runtime source and not ACTIVE.

- `pilot-v1.6.2.json` — the phase B2 pilot slice, built by
  `tools/knowledge_kb/build_pilot_seed.py` from the Knowledge Library v1.6.2 Google Sheet
  (Drive file `1So1_YjY4DRKbFMALybKPyWcdcBd-EmL7_3OaCzQ71rA`; the export SHA-256 is recorded
  in the seed). It contains what v1.6.2 proposed. The loader
  `jewelai_persistence.knowledge_kb_pilot.load_seed` re-qualifies every record by its
  validation profile before anything can be published.

Slice: corundum (ruby, sapphire) constants, care and reference rows; round-diamond Stuller
points and separate Dalila ranges; RU → US/EU/UK/JP ring sizes and the metric carat; gold
fineness ↔ karat; three GOST 30649-99 alloy densities and the generic Ag 925 / Pt 950 rows.
