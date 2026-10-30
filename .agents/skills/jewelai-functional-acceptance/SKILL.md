---
name: jewelai-functional-acceptance
description: Independently review, verify regressions or functionally accept JewelAI V2 text-only Prompt Enrichment on an exact PR HEAD using code inspection and adversarial raw-text-to-output evidence. Use in a separate read-only reviewer session, not for implementing or repairing defects.
---

# JewelAI independent functional acceptance

Read [AGENTS.md](../../../AGENTS.md) and its current protocol/backlog/Boundary references. Operate as a separate reviewer: Development's own walkthrough is not independent acceptance. Keep application source and repository configuration READ-ONLY. Do not repair defects, create commits, merge, deploy or activate Knowledge. A review verdict does not itself authorize those actions.

## Ground the independent review

1. Verify the live PR target, base and exact HEAD SHA, Draft/merge state, working-tree cleanliness and relevant merged dependencies. Record the tested SHA; do not reset unrelated changes. If HEAD changes, stop acceptance until the affected inspection/tests and fresh CI are reconciled.
2. Read original requirements, approved contracts/ADRs and acceptance criteria independently, then inspect the actual diff, consumers and tests. Treat developer summaries as leads, never proof. Separate current evidence from historical backlog claims and synthetic qualification from professional Knowledge authority.
3. Derive additional adversarial scenarios from the intended user outcome and cross-feature invariants, beyond developer cases. Include RU/EN and mixed rephrasings, reordered/multiline statements, positives beside negations, center/side/component ownership, uncertainty, same-target conflict, independent metal/stone changes and unrelated constraints as applicable. Do not invent the expected resolution of an undefined policy; request a precise Owner decision instead.

## Observe the complete affected journey

- Use the existing raw-text HTTP lifecycle and TEST-ONLY fixtures. Compare original source text/Message spans → Parser interpretation and object relationships → Dictionary/Knowledge bindings → Matrix decisions → actual canonical Product State before/after → clarification/correction → readable description → Internal Final Prompt. HTTP 200 or a correct isolated function is insufficient.
- Challenge LOCK/KEEP and confirmed authority, recommendations versus accepted facts, missing/unknown/unsupported values, rejected/ambiguous text, independent positive facts and contradictions. Inspect provenance, supersession, immutable prior history, release pin and final-output fidelity. Never accept a description contradicting canonical facts merely because structured IFP is correct.
- Exercise multiple persisted corrections/answers, stale CAS/no partial write, restart/restoration and organization/session isolation where relevant. Record database backend and what was actually restored. Use safe ephemeral test data only; keep outputs outside tracked source and verify the tree remains unchanged.
- Follow the [existing disposable PostgreSQL gate](../../../apps/api/tests/test_generation_preparations_postgres.py) before any DDL/destructive fixture. Do not point tests at an unverified database or live deployment. Use fake external boundaries; do not create live users/sessions or invoke providers without separate authorization.
- Check fresh GitHub CI on the exact reviewed SHA and inspect required skipped/failed steps. Green CI is technical evidence, not functional acceptance; retain independently reproduced counterexamples even when all developer tests pass. Explain unavailable access or unsafe checks instead of substituting assumptions.

## Evidence and verdict

For each required scenario record: exact SHA/backend, raw synthetic input and sequence, expected outcome/contract, observed Parser/binding/Matrix/state/output, relevant immutable source/history evidence, reproducible command or HTTP steps, and one evidence status:

| Status | Meaning |
| --- | --- |
| VERIFIED PASS | Reviewer directly observed the required behavior in the stated boundary. |
| VERIFIED FAIL | Reviewer directly observed a reproducible deviation. |
| SKIP | A selected check could not run; give the safety/access/dependency reason. |
| NOT TESTED | No independent execution was performed for this claim. |
| DEVELOPER-REPORTED | Only Development's report supports it; not independent proof. |

Report findings with expected/actual behavior, consequence, relevant code and reproduction. Separate observations from root-cause hypotheses; do not expose credentials, customer prompts/images, signed URLs or private provider payloads. Provide accessible evidence, remaining gaps and exact-head CI links for the existing single backlog, without creating a parallel tracker or claiming acceptance outside tested scope.

Recommend exactly one verdict: **APPROVE**, **CHANGES REQUIRED**, **BLOCKED**, or **INSUFFICIENT EVIDENCE**. APPROVE requires independent evidence for the agreed acceptance scope, no unresolved blocking findings and fresh relevant exact-head CI. A false PASS supported only by developer tests or green CI is **INSUFFICIENT EVIDENCE**, not APPROVE. A verified defect warrants CHANGES REQUIRED; a missing required Owner decision/access dependency may warrant BLOCKED. Leave implementation and remediation to Development and merge decisions to the independent coordinator.
