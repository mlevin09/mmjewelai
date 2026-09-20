# [V2] Implement Rules Engine v1

Read AGENTS.md, ARCHITECTURE.md and specs/rules/README.md on jewelai-v2. Branch from and target PRs to jewelai-v2.

## Dependencies
All preceding four foundation issues.

## Acceptance criteria
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

## Definition of done
- [ ] Versioned contract and scoped implementation.
- [ ] Meaningful positive/negative tests, documented run command.
- [ ] Cross-references validated and domain-review decisions explicit.
- [ ] PR and updated specifications; preserve V1 files.

Exclude frontend, image generation, provider calls, persistence and infrastructure.
