# Rules Engine v1 — implementation brief

Input: versioned validated design state, role, catalog bundle and available sourced KB facts.
Output: decision (ask/derive/assume/block/ready), field and question IDs, rule ID/version, reason and proposed state changes.
Rules must be declarative with an allowlisted condition/action vocabulary; no eval or arbitrary code in catalogs.
Define deterministic priority/tie order, bounded evaluation, conflict handling and stable replay.
Missing mandatory data blocks readiness. Optional questions must not prevent completion indefinitely.
Locked values cannot be overwritten. Assumptions are disclosed; derivation requires source and uncertainty.

Acceptance scenarios:
- Ring with emerald 3 ct, missing shape: ask shape; no invented dimensions.
- Retail with sufficient sourced KB match: propose an explicitly derived estimate.
- Industrial designer lacking exact dimensions: ask for actual measurements.
- Conflicting update to locked metal: block/explain.
- No valid KB match: ask or retain unknown, never fabricate.
- Fully satisfied required fields: ready; repeated input yields identical result.
- Cyclic rules, conflicting actions and unknown references fail with bounded, explainable outcomes.

Deliver rule schema/catalog loader, gap analyzer, evaluator, decision traces and offline tests. No LLM/API/cloud calls.
