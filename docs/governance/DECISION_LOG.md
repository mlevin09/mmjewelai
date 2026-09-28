# JewelAI Decision Log

Status: Working
Last reviewed: 2026-09-28

## Policy

This log records material, durable, explicitly recorded team decisions affecting product direction, cross-product architecture, security/data policy, commercial structure, material operational policy, governance, or another durable project constraint.

Routine implementation choices remain in code, issues, pull requests, ADRs, or technical documentation unless they create a durable project-level constraint.

Repository ADRs keep their own statuses.

## Status vocabulary

- PROPOSED
- WORKING
- ACCEPTED — use for Project-level decisions only after explicit approval authority/action is defined
- REJECTED
- SUPERSEDED
- DEPRECATED
- HISTORICAL / NEEDS CONFIRMATION

## Working governance conventions

### GOV-W01 — No implicit Project-document acceptance

Drive/Project documents, specifications, benchmarks, roadmaps, presentations, and research are not Accepted solely because they exist, appear mature, or are currently used.

Repository records with their own explicit lifecycle retain that status within their scope.

### GOV-W02 — Product priority remains open

No existing JewelAI product is treated as the first development priority, primary product, or default entry point without an explicit recorded team decision.

### GOV-W03 — GitHub governance is canonical

The version-controlled files under `docs/governance/` are the canonical governance copy.

Project Sources/Drive may provide a readable mirror or knowledge layer. If a mirror differs, the repository version governs.

### GOV-W04 — Live systems retain operational authority

`CURRENT_STATE.md` summarizes current state but does not replace the repository, GitHub issues/PRs, deployment configuration, infrastructure state, or other live operational systems.

### GOV-W05 — Historical MVP decisions are not auto-migrated

Decision cells in historical MVP planning artifacts remain historical evidence unless independently validated against current product strategy and explicitly recorded through the current decision process.

See `reviews/MVP_0_1_DECISION_REVIEW.md`.

### GOV-W06 — Vibe coding is the default development mode

Date: 2026-09-27
Status: WORKING
Scope: JewelAI software-development workflow

**Decision**

JewelAI software development should default to an action-oriented vibe-coding workflow.

For routine coding work, the agent should execute through repository inspection, implementation, validation, PR preparation, and requested merge/continuation without repeatedly asking for confirmation.

The agent should resolve technical facts from tools and the repository first, make small reversible assumptions when needed, and ask the user only for genuinely blocking choices, credentials/permissions, irreversible/destructive authorization, or unresolved materially different product behavior.

**Consequence**

Project Instructions and the `jewelai-dev-task` Skill should optimize for low-interruption execution while preserving security, source-of-truth discipline, and risk-proportional verification.


---

## Working project decisions

### DEC-W01 — Environment lifecycle and isolated European preproduction baseline

Date: 2026-09-28  
Status: WORKING  
Scope: Deployment architecture and operational environment model

**Decision**

JewelAI uses the environment lifecycle `Local development -> Preproduction -> Production`.

Preproduction is a real isolated application environment, not a Terraform-plan pseudo-environment. It uses the dedicated GCP project `mmjewellai-preprod`, regional baseline `europe-west1`, private Asset location `EUROPE-WEST1`, a distinct bootstrap/state/WIF/deployer boundary, and one GitHub Environment named `preprod` for both Terraform plan and apply stages.

Preproduction intentionally has no required-reviewer or prevent-self-review gate so the vibe-coding workflow can execute end-to-end. Exact-SHA, exact-project, WIF, immutable-image, private-state, saved-plan checksum/configuration/object-generation binding, and no-replanning controls remain mandatory.

Production configuration and protections are separate and are not weakened by this decision.

**Context**

A separate `preprod-plan` GitHub Environment duplicated configuration without representing a distinct runtime environment. The expected first users are primarily in Europe and Israel, so the preproduction regional baseline was moved from `us-central1` to `europe-west1` before first deployment.

**Consequences**

Preproduction infrastructure must stay isolated from production and must not reuse production Terraform state, deployment identities, domains, or secrets. Preproduction runtime/storage defaults should remain European unless a later explicit decision changes them.

**Related sources**

- ADR 0023: `docs/adr/0023-preproduction-deployment.md`
- PR #35 — single `preprod` GitHub Environment
- PR #36 — Europe regional baseline
- PR #37 — isolated preprod bootstrap
- PR #38 — repeatable preprod bootstrap IAM correction

**Supersedes**

The earlier `preprod-plan` + `preprod` GitHub Environment model.

**Superseded by**

None.

---

### DEC-W02 — Google Cloud Identity Platform is the preproduction identity provider

Date: 2026-09-28  
Status: WORKING  
Scope: Preproduction authentication architecture

**Decision**

JewelAI preproduction uses Google Cloud Identity Platform / Firebase Authentication instead of provisioning Auth0.

The browser uses the official Firebase Authentication SDK. The initial preproduction provider is email/password with session persistence; anonymous authentication is disabled. The browser sends Firebase ID tokens as bearer tokens. The API verifies the Google/Firebase token signature and the project-specific issuer/audience contract for `mmjewellai-preprod`.

Identity Platform establishes authenticated identity only. PostgreSQL remains authoritative for JewelAI organization membership, roles, tenant authorization, and application permissions.

**Context**

No live preproduction Auth0 tenant, Auth0 resources, or Auth0 users existed, so there was no migration requirement. Using the existing GCP identity service removes a separate external Auth0 bootstrap/billing dependency for preproduction.

**Consequences**

Preproduction Auth0 Terraform resources and GitHub Auth0 secrets are removed. Public Firebase client configuration may be injected into the web runtime because it is not a server secret. Service-account private keys and provider secrets must never be exposed to the browser.

This decision applies to preproduction only. Production retains its current OIDC/Auth0-capable path until a separate production identity decision is explicitly made.

**Related sources**

- PR #39 — Identity Platform preproduction implementation
- ADR 0023: `docs/adr/0023-preproduction-deployment.md`
- `packages/auth_identity_platform/`
- `infra/terraform/preprod/identity_platform.tf`

**Supersedes**

The unprovisioned preproduction Auth0 plan.

**Superseded by**

None.

---

### DEC-W03 — `jewellai.online` preproduction hostnames use external DNS handoff

Date: 2026-09-28  
Status: WORKING  
Scope: Preproduction public addressing and DNS ownership

**Decision**

The JewelAI domain is `jewellai.online` and the preproduction public hostnames are:

- web: `preprod.jewellai.online`
- API: `api.preprod.jewellai.online`

For the current preproduction deployment, DNS remains externally/operator managed. `DNS_MANAGED_ZONE` is intentionally unset rather than inventing or creating a Cloud DNS zone without an explicit DNS-ownership decision.

**Consequences**

Terraform creates the public load-balancer address and Google-managed certificate resources, then emits the required DNS records for external creation. HTTPS verification must wait for DNS propagation and certificate activation.

The load-balancer IP is operational state, not a durable decision, and belongs in `CURRENT_STATE.md` rather than this Decision Log.

**Related sources**

- `infra/terraform/preprod/networking.tf`
- `infra/terraform/preprod/outputs.tf`
- successful preproduction deployment run `36426056821`

**Supersedes**

None.

**Superseded by**

None.
