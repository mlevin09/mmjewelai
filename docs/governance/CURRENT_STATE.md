# JewelAI Current State

Status: Working
Last reviewed: 2026-09-28

> Navigational snapshot only. Verify volatile repository, CI/CD, deployment, infrastructure, provider, pricing, and external facts at the source.

## Executive state

JewelAI is being developed as an AI-native modular ecosystem for the jewelry industry.

Product prioritization remains open. No existing product is designated as the first development priority, primary product, or default ecosystem entry point.

Repository ADRs retain their own explicit engineering statuses.

## Development mode

As of 2026-09-27, JewelAI development uses **vibe coding as the default software-development workflow**.

The desired agent behavior is:
- execute rather than repeatedly ask for routine confirmation;
- verify repository/tool state directly;
- use small reversible assumptions for non-blocking uncertainty;
- inspect only relevant sources first;
- continue through implementation, tests, PR, and requested merge/next step;
- ask only for genuine blockers, secrets/permissions, destructive authorization, or unresolved materially different product behavior.

## Active repository state

Repository: `mlevin09/mmjewelai`

Current V2 integration branch:
- `jewelai-v2`
- deployed preproduction SHA: `8d7a48a3a1b5158bb8cb3a66d0f20af3977eb393`
- current head: verify live in GitHub after this governance refresh

PR #39 replaced the unprovisioned preproduction Auth0 dependency with Google Cloud Identity Platform while preserving the provider-neutral production OIDC path.

The first real preproduction deployment then required corrective PRs #40-#46 before reaching a
successful applied state. PRs #48-#49 completed push-triggered HTTPS verification and corrected the
live Google output media-type contract. These corrections are part of current implementation
reality and must remain visible in handoff context.

## Preproduction platform

Preproduction is provisioned and deployed in a dedicated GCP project.

Current baseline:
- GCP project: `mmjewellai-preprod`
- primary region: `europe-west1`
- private Asset bucket location: `EUROPE-WEST1`
- web hostname: `preprod.jewellai.online`
- API hostname: `api.preprod.jewellai.online`
- DNS mode: external/operator-managed
- GitHub Environment: single `preprod` environment for Terraform plan and apply
- Terraform state prefix: `preprod/platform`

The isolated preproduction bootstrap provides the dedicated Terraform state bucket, regional Artifact Registry repository, branch-bound GitHub Workload Identity Federation provider, and keyless `jewelai-preprod-deployer` service account.

The latest deployment verified on GitHub is `Deploy preprod` run `36593355997` on exact SHA
`8d7a48a3a1b5158bb8cb3a66d0f20af3977eb393`. Both plan and apply completed successfully. Exact
saved-plan binding checks passed, Terraform apply completed, the database migration job completed,
Identity Platform readiness verification passed, the managed certificate was `ACTIVE`, and both
public HTTPS health checks passed.

PR #48 passed Runtime API, Web, Terraform, and container checks before merge. PR #49 passed the
Runtime API workflow in run `36436828196` before merge. For the Identity Platform implementation
itself, PR #39 and its merge commit both had successful Runtime API, Web, and Infrastructure
workflows.

### Preproduction identity

Preproduction authentication uses Google Cloud Identity Platform / Firebase Authentication.

Current contract:
- browser library: official Firebase Authentication SDK
- initial provider: email/password
- browser persistence: session persistence
- anonymous authentication: disabled
- authorized browser domain: `preprod.jewellai.online`
- bearer transport: Firebase ID token in the Authorization header
- expected issuer: `https://securetoken.google.com/mmjewellai-preprod`
- expected audience: `mmjewellai-preprod`
- API verification: Google-supported Firebase token verification through `google-auth`
- PostgreSQL remains authoritative for organization membership, roles, tenant authorization, and application permissions

Preproduction Auth0 Terraform resources and Auth0 workflow secrets were removed. Production retains its existing OIDC/Auth0-capable path until a separate production identity decision.

### Preproduction generation provider

The current preproduction generation profile enables the Google Generative Language image provider and leaves OpenAI disabled.

Reviewed Google image-model allowlist:
- `gemini-3.1-flash-lite-image`
- `gemini-3.1-flash-image`
- `gemini-3-pro-image`

The Google API key remains in GCP Secret Manager under
`jewelai-preprod-google-generative-language-api-key`; it is not stored in GitHub variables or
browser/runtime configuration. PR #43 records creation of corrected enabled secret version 2, and
the successful final deployment preflight independently verified that an enabled secret version
was available.

The bounded live generation smoke selected provider `google` and model
`gemini-3.1-flash-lite-image`, completed successfully, and finalized a private generated Asset as
`ready`. Live evidence showed that this Google model returns `image/jpeg`; PR #49 preserves that
declared type, verifies its JPEG signature, and carries it through the existing Asset boundary
without relabeling or conversion.

### First-deployment corrective sequence

The successful deployment depended on these merged corrections after PR #39:
- PR #40 — added an auditable `jewelai-v2` push-based preproduction deployment-request trigger because the workflow is not registered for `workflow_dispatch` while it exists only on the non-default branch.
- PR #41 — granted the preproduction deployer the IAM role-administration capability required for bounded custom-role creation.
- PR #42 — selected Cloud SQL `ENTERPRISE` edition for compatibility with the configured PostgreSQL 16 `db-custom-*` tier.
- PR #43 — corrected the Google API-key Secret Manager payload and created enabled version 2 without edge whitespace.
- PR #44 — repaired/retried the worker deployment after the initial worker startup failure.
- PR #45 — finalized deployment after first-run provider dependency expansion produced a concrete worker URI.
- PR #46 — removed unsupported explicit backend timeout configuration for the API serverless NEG path.
- PR #48 — made the audited push trigger carry a validated `verify_external_dns_https` boolean from
  plan to apply.
- PR #49 — preserved signature-validated PNG/JPEG/WebP across the transient provider boundary after
  the live Google model returned JPEG.

### External DNS handoff

The successful deployment emitted these required A records:
- `preprod.jewellai.online` -> `8.233.118.174`
- `api.preprod.jewellai.online` -> `8.233.118.174`
- TTL: 300 seconds

Public DNS now resolves both hostnames to `8.233.118.174`. Independent checks against public DNS
confirmed the web and API records, and the deployment readiness check confirmed both names resolve
to the load balancer.

The Google-managed certificate `jewelai-preprod-managed` is `ACTIVE`. Both
`https://preprod.jewellai.online/health` and `https://api.preprod.jewellai.online/health` return HTTP
200 with the expected healthy response.

### Live identity, authorization, and generation verification

PR #48 closed the push-trigger gap. The closed request schema accepts a boolean
`verify_external_dns_https`, the plan job emits the validated value, and apply consumes that exact
job output while retaining exact-SHA and project guards.

A bounded live smoke on deployed SHA `55ce94eb2f5f2e286341e7144a26b359bf076fc4`
confirmed:
- Firebase email/password sign-in and logout;
- valid Firebase ID-token acceptance by the API;
- stable `/me` principal resolution;
- an authenticated principal without membership received the scoped 404 denial;
- explicit PostgreSQL membership enabled the approved organization path;
- one normal Google generation succeeded through queue, worker, provider, private object staging,
  GenerationRun completion, and Asset finalization;
- the generated Asset reached `ready` with validated `image/jpeg` content.

Temporary Identity Platform smoke users were deleted after the test. No credential, bearer token,
prompt, image payload, API key, or signed URL was recorded in this governance snapshot.

### MVP Text Intake v1 live verification

PR #52 added the natural-language intake boundary. A Google Generative Language adapter returns
only an untrusted `ParserCandidate`; the existing deterministic Parser Proposal, revision/CAS,
Rules Engine, Question Catalog, Prompt Compiler, generation, and Asset boundaries retain authority.
PR #54 subsequently bound failed deployment-job retries to the exact private plan-object output,
preventing `GITHUB_RUN_ATTEMPT` path reconstruction from losing the reviewed plan.

The bounded live smoke on deployed SHA `8d7a48a3a1b5158bb8cb3a66d0f20af3977eb393`
confirmed:
- temporary Identity Platform email/password sign-in and stable `/me` resolution;
- scoped denial before PostgreSQL membership and successful access after explicit membership;
- persistence of the original English jewelry request;
- untrusted candidate normalization/application through Parser Proposal and revision CAS;
- deterministic clarification followed by the existing READY decision;
- immutable prompt compilation and one Google generation through the normal queue/worker path;
- successful GenerationRun completion and generated Asset finalization as `ready`.

The final short-lived signed-read request returned the redacted `asset_access_unavailable` 503, so
browser image-view verification is not claimed. Live configuration and IAM inspection found the
expected dedicated signer identity, exact `iam.serviceAccounts.signBlob` custom permission, binding
from the API identity to the signer, enabled IAM Credentials API, and correct API runtime identity.
Resolving this existing preproduction signing failure is the remaining operational blocker before
Text Intake v1 can be called fully live-verified. Temporary Identity Platform smoke users were
deleted, and the temporary organization membership was removed. No token, credential, prompt,
image payload, API key, or signed URL was recorded.

## Production platform

Production Terraform and deployment workflow behavior were not changed by the preproduction Identity Platform rollout or the first-deployment corrective sequence.

Production infrastructure definitions remain in the repository, but actual production provisioning state must be verified independently against live production systems before making production claims.

No decision has been made to migrate production authentication from its existing OIDC/Auth0-capable path to Identity Platform.

## ChatGPT Project configuration

Project Instructions, governance sources, and four JewelAI Skills are installed.

For routine coding, the optimized rule is now:
**repository first; Project Sources only when product/domain intent or governance is actually needed.**

Installed Skills:
- `jewelai-dev-task`
- `jewelai-release-readiness`
- `jewelai-visualization-benchmark`
- `jewelai-product-decision`

GitHub `docs/governance/` remains canonical; Project Sources are a readable knowledge mirror.

## Product state

Multiple JewelAI product concepts and modules exist in project documentation. Their existence or documentation maturity does not establish current development priority.

## Visualization state

`JewelAI_Vision_Core.pdf` is a primary Working reference within visualization-core scope.

`JewelAI_Retail_Vision_Spec.pdf` is a primary Working reference within Retail visualization scope and does not imply Retail product priority.

Repository V2 implementation may be more current than Drive documents for implemented runtime behavior.

## Benchmark state

Visualization benchmark methodology is Working.

`JewelAI_Visualization_Benchmark_Scenarios_v1.3.docx` has a filename/internal-version mismatch to correct when next revised.

## Customer discovery

`JewelAI_CustomerDiscovery_опросник.docx` is a primary Working methodology reference.

## Historical MVP map review

The historical MVP spreadsheet contains 87 populated decision cells. They remain historical planning evidence unless explicitly revisited.

See `reviews/MVP_0_1_DECISION_REVIEW.md`.

## Next operational actions

1. Define who may assign Project-level `Accepted` status.
2. Refresh the Project Sources governance mirror after canonical governance updates.
