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
- deployed preproduction SHA: `7c6195cd17c6a14f44ce8b462fb5504abf8b4f12`
- current head: verify live in GitHub after this governance refresh

PR #39 replaced the unprovisioned preproduction Auth0 dependency with Google Cloud Identity Platform while preserving the provider-neutral production OIDC path.

The first real preproduction deployment then required corrective PRs #40-#46 before reaching a successful applied state. These corrections are part of current implementation reality and must remain visible in handoff context.

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

The final deployment verified on GitHub is `Deploy preprod` run `36426056821` on exact SHA `7c6195cd17c6a14f44ce8b462fb5504abf8b4f12`. Both plan and apply completed successfully. Exact saved-plan binding checks passed, Terraform apply completed, the database migration job completed, and Identity Platform readiness verification passed. HTTPS smoke checks were skipped by design because external DNS had not yet been created.

Infrastructure CI also passed on the same final SHA in run `36426056908`. For the Identity Platform implementation itself, PR #39 and its merge commit both had successful Runtime API, Web, and Infrastructure workflows.

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

The Google API key remains in GCP Secret Manager under `jewelai-preprod-google-generative-language-api-key`; it is not stored in GitHub variables or browser/runtime configuration. PR #43 records creation of corrected enabled secret version 2, and the successful final deployment preflight independently verified that an enabled secret version was available.

### First-deployment corrective sequence

The successful deployment depended on these merged corrections after PR #39:
- PR #40 — added an auditable `jewelai-v2` push-based preproduction deployment-request trigger because the workflow is not registered for `workflow_dispatch` while it exists only on the non-default branch.
- PR #41 — granted the preproduction deployer the IAM role-administration capability required for bounded custom-role creation.
- PR #42 — selected Cloud SQL `ENTERPRISE` edition for compatibility with the configured PostgreSQL 16 `db-custom-*` tier.
- PR #43 — corrected the Google API-key Secret Manager payload and created enabled version 2 without edge whitespace.
- PR #44 — repaired/retried the worker deployment after the initial worker startup failure.
- PR #45 — finalized deployment after first-run provider dependency expansion produced a concrete worker URI.
- PR #46 — removed unsupported explicit backend timeout configuration for the API serverless NEG path.

### External DNS handoff

The successful deployment emitted these required A records:
- `preprod.jewellai.online` -> `8.233.118.174`
- `api.preprod.jewellai.online` -> `8.233.118.174`
- TTL: 300 seconds

At the 2026-09-28 review, an independent DNS lookup returned no IPv4 resolution for either hostname. DNS creation/propagation remains incomplete.

After the records resolve, the Google-managed certificate must become `ACTIVE` before public HTTPS smoke checks and browser authentication smoke tests can complete.

### Verification-trigger gap discovered during review

The current fallback deployment trigger has one remaining technical inconsistency:
- the `jewelai-v2` push path is currently the usable trigger because GitHub does not register this workflow for manual dispatch while the workflow exists only on the non-default branch;
- `.github/preprod-deployment-request.json` is currently validated on push with `verify_external_dns_https == false`;
- therefore the documented post-DNS rerun with `verify_external_dns_https=true` cannot currently be exercised through that push fallback.

This is a small workflow defect to fix before autonomous post-DNS HTTPS verification.

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

1. Create the two external DNS A records for `preprod.jewellai.online` and `api.preprod.jewellai.online` pointing to `8.233.118.174`.
2. Fix the preproduction request/verification trigger so post-DNS HTTPS verification can be requested through the usable `jewelai-v2` path.
3. Wait for DNS propagation and Google-managed certificate activation, then run HTTPS readiness and health checks.
4. Run bounded Identity Platform smoke tests: sign-in, bearer authentication, `/me`, denial without membership, approved membership, and logout.
5. Run one bounded Google generation smoke test through the normal JewelAI path and verify Asset finalization without exposing prompt/image/key data.
6. Define who may assign Project-level `Accepted` status.
7. Refresh the Project Sources governance mirror after canonical governance updates.
