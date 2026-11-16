# ADR 0045 — Declaration-owned PR checks and separate release evidence (EN MASTER)

Status: implementation proposed in PR #179; independent review pending.
Date: 2026-11-16. Assignment: CI-RISK-002.

## Context

The actual ROLES-001 diff (PR #178, fe5ec8466d2d6ca63a1fcb69483043aa0bbc3869)
selected 4,011 native cases. Its API group timed out at 1,200 seconds, despite
passing the directly relevant role/migration/HTTP cases. File-prefix bucket unions,
whole-package Domain/Parser/Prompts expansion and transitive test-file imports
were not accurate measures of the changed behavior. A separate post-execution
Full requirement prevented a complete targeted PR run from succeeding.

## Decision

Keep the existing pytest runner, case accounting, 800-case guardrail, PostgreSQL
identity gate, required Runtime API job and manual Full workflow. Routing v2 uses
changed Python declarations and explicit component ownership. Changed test functions
include all native parameters. Unknown shared declarations, resources and helpers
block with paths and names; they do not fall back to broad-prefix guesses.

Current shared bootstrap and test-support transitions have reviewed semantic
before/after source-hash pairs plus contract/integration ownership. These are CI
coverage registrations, not product compatibility paths or arbitrary future fixture
exemptions. A later edit invalidates the pair and blocks. Imports alone never prove
complete resource ownership. New source families require evidenced registration.
The v1 synthetic fixture-policy tests remain supported; the repository's active
configuration is v2. No v2 failure falls back to v1 routing.

A complete successful targeted PR run returns PASS while explicitly recording
NOT_QUALIFIED release status. Only validated Full receipt plus read-only GitHub
metadata on the exact release SHA can qualify a release. No automatic Full dispatch,
coverage skip, status override or branch-protection mutation is introduced.

## Owner gate: release enforcement

The existing preprod deployment workflow does not consume a Full receipt. Moving
that enforcement into the protected deployment path is a material rule change.
`tools/ci/release-gate.proposed.patch` is a tested, unapplied minimal proposal:
locate a successful exact-SHA Full run, download its attempt-bound receipt and
validate all coverage/authorization metadata before GCP authentication or image
build. Missing, failed, expired or mismatched evidence must block the release.
The read-only `qualification.py latest` discovery is implemented and tested.

**Owner must approve the deployment-rule insertion before integration/activation
of the separation.** The patch is not applied; neither preprod nor production
workflow is changed here. Existing deployment-request SHA/exact-plan safeguards
remain intact. A PR PASS is not evidence that this release condition is enforced.

## Alternatives and consequences

Rejected: raising timeouts/caps, dropping failing tests, import-reader inference,
PR-number exceptions and automatically executing Full Regression. Source-pair
coverage requires explicit review for a future shared fixture change; this
conservative maintenance cost is preferable to silently missing consumers.

A dedicated reference qualification workflow reuses the same runner on the exact
ROLES source with only candidate CI tooling/workflow overlays. It reports both
subject SHA and selector SHA and cannot qualify a release or override PR #178's
required status. Its descriptor changes trigger the bounded measurement; ordinary
CI-only Runtime checks do not execute API bodies. No product files or shared data
are modified, and all PostgreSQL execution remains serial and independently gated.
