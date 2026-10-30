---
name: jewelai-functional-development
description: Implement or repair an approved JewelAI V2 text-only Prompt Enrichment functional outcome end to end, including investigation, technical decomposition, regression tests and a Draft PR. Use for functional development and review-requested fixes; not for independent acceptance or deployment.
---

# JewelAI functional development

Read [AGENTS.md](../../../AGENTS.md) for current scope, working protocol, single backlog and Owner gates. Load this skill for implementation, not to certify independent acceptance. Follow the current approved assignment; a completion-program entry alone is not authorization to start its implementation.

## Establish the behavior contract before edits

1. Fetch and record the live `jewelai-v2` baseline, working tree and relevant dependencies/PRs. For an existing PR, verify its exact HEAD and continue its branch unless instructed otherwise; do not replace or overwrite concurrent work.
2. Read the approved outcome, original input/expected output, relevant contracts/ADRs and actual consumers/tests. Reconstruct the affected raw-text → Parser → Dictionary/Knowledge → Matrix/Rules → canonical Product State → clarification/correction → description/IFP journey. Separate observed failures from hypotheses and developer reports.
3. State the expected user-visible outcome and cross-feature invariants before coding. Trace explicit facts, negation and uncertainty to the correct object/target; preserve independent positive requirements, LOCK/KEEP, confirmation, source Message IDs/spans, immutable history, release pins and revision/CAS. Omission is not permission to reset state. Description and IFP must agree with authoritative accepted facts without losing unresolved requests or inventing dimensions.
4. Build the technical plan autonomously around shared root causes and complete approved outcomes, including dependencies, risks and verification. Do not reduce a class of failures to regex patches for reported strings. Distinguish a correction under existing approved authority from a new conflict, cancellation, Unknown or acceptance policy. For undefined semantics, stop the affected work and present the smallest concrete Owner decision; do not invent it.

## Implement and verify the approved block

- Reuse existing parser/proposal, Knowledge, Matrix/Policy, revision/CAS and rendering boundaries. Keep source-backed knowledge separate from accepted user requirements. Do not make a library match, recommendation or test-only fixture an authority bypass.
- Reproduce the defect before changing behavior where practicable; record actual RED and GREEN outcomes. Add unseen positive, negative, adversarial and combined scenarios, not only the reported phrases. Include RU/EN and mixed input where applicable, statement/property scope, center/side/component ownership, unrelated changes, protected facts and ambiguous/rejected follow-ups.
- Use the existing unit/integration tests and real persisted HTTP lifecycle for affected behavior: inspect candidate interpretation/binding, Matrix decisions, state before/after, source/constraint evidence, clarification, correction, description and final IFP. Cover multiple messages, restart/restoration, stale CAS/no partial append and tenant scope where applicable. Preserve historical hashes and supersession lineage. Explain any inapplicable boundary.
- Apply [existing database test conventions](../../../apps/api/tests/test_generation_preparations_postgres.py). Never infer disposability from a database name or environment variable; do not run destructive setup without the existing independent container/cluster gate. A local PostgreSQL SKIP is not PASS. Keep provider/network calls fake; no paid calls or real catalog activation.
- Run repository-native checks appropriate to the changed areas. Inspect the complete diff for unrelated changes; self-review state/output consistency, contract compatibility and tests. Push the scoped branch, create/update one coherent Draft PR into `jewelai-v2`, and inspect fresh CI on its exact HEAD. A changed HEAD invalidates older review/CI evidence.

## Evidence and handoff

Report exact baseline/final SHA, branch/PR, changed production files, invariant/root cause, representative inputs and actual before/after state/output, reproducible commands, test/CI links and results. Label PASS, FAIL, SKIP, NOT TESTED and unsupported claims explicitly; include remaining bugs, limitations and STOP decisions. Keep secrets/private content out of evidence and provide Owner-accessible evidence rather than relying solely on an inaccessible temporary path. Use the existing single backlog through authorized updates; do not invent a second tracker.

Finish at an open Draft PR for a separate independent acceptance session. Implementation complete is not FUNCTIONAL ACCEPTED, merged or deployed. Do not self-merge, mark Ready, enable auto-merge, deploy or activate releases. No new testing platform, parallel architectural model, professional catalog work or unrelated feature expansion.
