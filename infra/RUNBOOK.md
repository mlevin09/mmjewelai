# JewelAI production runbook

Production operations are manual, reviewed, and credential-safe. Never paste tokens, signed URLs, database URLs, provider responses, prompts, or secret values into terminals recorded for issues or pull requests.

## Initial bootstrap

1. Create or select a billed GCP project and choose one primary region.
2. Create or select an Auth0 tenant. Create a least-privilege Auth0 Management API machine-to-machine client for Terraform; the tenant/account itself is not Terraform-managed.
3. Copy `infra/terraform/bootstrap/terraform.tfvars.example` outside Git, review the plan, and apply the bootstrap stack with an authorized operator identity.
4. Configure GitHub Environments named `production-plan` and `production` with identical non-secret project, region, registry, state bucket, WIF provider, deploy-service-account, domains, optional DNS zone, Asset bucket, `GENERATION_PROFILES_JSON`, `OPENAI_ALLOWED_MODELS`, and optional `GOOGLE_GENERATIVE_LANGUAGE_ALLOWED_MODELS` variables. The profile registry and exact provider worker allowlists must agree; leave the Google variable unset or empty to disable it. Add identical `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, and `AUTH0_CLIENT_SECRET` secrets. Both environments must have a deployment branch policy, require at least one production reviewer, and prevent self-review; the workflow independently reads the actual `production-plan` and `production` configurations through the GitHub API and fails before cloud authentication if any protection is missing. The exact workflow ref check remains restricted to `jewelai-v2`. This protection is mandatory because the plan job receives Auth0 management credentials and the production Terraform identity.
5. For the first deployment only, apply the production OpenAI Secret Manager metadata target after review, then seed a version without Terraform: `gcloud secrets versions add jewelai-production-openai-api-key --data-file=-`. If Google is enabled, also apply its secret metadata target and seed `jewelai-production-google-generative-language-api-key` the same way. Do not enter either value into tfvars or command history. The normal deploy preflights enabled versions for configured providers.
6. Confirm the existing Cloud DNS zone/domain inputs, or leave `DNS_MANAGED_ZONE` unset/empty. External DNS deployments emit the exact required A-record names and load-balancer IP after apply.
7. Dispatch `Deploy production` from `jewelai-v2` and enter its exact SHA. After approving the protected plan stage, review its one-day `production-plan-review-<SHA>` artifact and plan log, then approve the waiting `production` apply job. GitHub stores only Terraform's redacted text rendering. The exact binary plan stays in the private state bucket, and the apply job verifies its checksum, SHA-derived object path, image digests, and configuration fingerprint before applying without re-planning.
8. Create the first controlled-alpha Auth0 database user administratively. Terraform never stores users or passwords.
9. Open the web URL, sign in, and create the first JewelAI organization. Auth0 establishes identity only; PostgreSQL membership remains authorization authority.

No local developer task should apply either stack or mutate Auth0, GCP, DNS, users, or secrets.

## Preproduction setup and deploy

Preproduction is isolated from production and is deployed only by the manual `Deploy preprod`
workflow from `jewelai-v2`. Its regional baseline is `europe-west1`, with the private Asset bucket
in `EUROPE-WEST1`.

1. Apply `infra/terraform/preprod-bootstrap` once with an authorized operator identity after
   reviewing its saved plan. Supply the operator IAM member outside Git. The stack creates the
   isolated state bucket, `jewelai-preprod` repository, branch-bound WIF provider, and
   `jewelai-preprod-deployer`. Keep its ignored local bootstrap state with the operator; the main
   preproduction platform uses the created bucket's private `preprod/platform` prefix.
2. Configure the single GitHub Environment `preprod` with a non-null deployment branch policy
   restricted to `jewelai-v2`. Preproduction intentionally does not require reviewers or
   prevent-self-review so the agent-owned workflow can complete autonomously. Its configuration
   must include
   `GCP_PROJECT_ID=mmjewellai-preprod` and matching region, registry, state bucket, WIF deployer,
   domains, Asset bucket, Auth0 credentials, OpenAI allowlist, and generation profiles.
3. Ensure `GENERATION_PROFILES_JSON` contains at least one Google profile using one of the three
   workflow-pinned Google image models. The workflow rejects a catalog with no executable Google
   profile.
4. Confirm `jewelai-preprod-google-generative-language-api-key` exists in the preproduction project
   with an enabled version. The workflow references this existing secret; it never creates, reads,
   prints, or transports the value. OpenAI is optional in preproduction; an empty
   `OPENAI_ALLOWED_MODELS` omits its secret, IAM, worker environment, and preflight.
5. Dispatch `Deploy preprod` from the exact green `jewelai-v2` SHA. The plan and apply jobs both use
   the single `preprod` Environment. The separate apply stage consumes the
   checksum/configuration-bound plan produced by the plan stage without re-planning.
   Redacted plan output remains available for inspection. State is isolated under
   `preprod/platform`; the workflow fails
   if the configured project is anything other than `mmjewellai-preprod`.
6. Complete the same managed-DNS readiness or external-DNS handoff used by production, then perform
   one bounded Google generation smoke test. Verify the selected provider/model lineage, private
   Asset finalization, and absence of prompt/image/API-key content in logs.

Never reuse the `production-plan` or `production` GitHub Environments, production state prefix,
production domains, or production secrets for this workflow.

## Normal deploy

1. Verify Runtime API, Web, and Infrastructure checks are green on the exact `jewelai-v2` SHA.
2. Dispatch the protected workflow with that SHA and authorize the mandatory `production-plan` protection gate. The plan job authenticates through WIF, builds and pushes SHA-tagged images, resolves registry digests, and creates a saved Terraform plan using only `@sha256` image references.
3. Review the plan log and one-day redacted-text artifact. Confirm no unexpected IAM, DNS, data-destruction, or secret-version changes, then approve the waiting `production` job. The exact binary is a create-only object under the private state bucket's `deployment-plans/` prefix, never a GitHub artifact. The apply job rejects a changed SHA-derived path, plan checksum, image reference, or protected configuration and applies the saved plan without re-planning. It deletes the live plan object after the apply attempt; the prefix lifecycle purges archived versions after one day.
4. The workflow applies and executes the migration job. With Terraform-managed DNS it polls DNS and managed-certificate state for at most 60 minutes before HTTPS smoke checks. With external DNS it prints the required A records and exits successfully without premature HTTPS checks.
5. Confirm migration output remains `0009_generation_asset_maint (head)` for this release, queue depth is healthy, worker request events appear, and real PKCE login succeeds.
6. Validate `/me`, organization selection, one bounded generation, and signed Asset display. Confirm the bearer token is the access token with the exact API audience—not the ID token.

For an external-DNS first deploy, create the emitted A records, wait for public propagation, then dispatch the same exact deployed SHA with `verify_external_dns_https=true`. Review and approve its exact (normally no-op) plan; the apply stage then requires certificate/DNS readiness and executes both HTTPS health checks. A bounded readiness timeout is a failed verification, not an infrastructure rollback signal.

Database migrations must follow expand/contract compatibility so old and new Cloud Run revisions can overlap safely.

## Rollback

Record the previous API, worker, and web digests before deployment. To roll back application code, supply those immutable digests to a reviewed Terraform deployment. Do not automatically downgrade Alembic: first determine whether the prior application remains compatible with the current schema. Cloud Run revision rollback is not a substitute for database analysis.

## Incident guides

- **API 5xx/high latency:** inspect the request-completion metric/logs by request ID, Cloud Run revision health, SQL saturation, and queue calls. Logs intentionally omit bodies and credentials.
- **OIDC unavailable:** check Auth0 status, exact issuer/JWKS reachability, SPA callback/origin settings, and access-token audience. Do not weaken issuer/audience checks.
- **Cloud SQL unavailable:** inspect instance/connection metrics, pool-budget formula, maintenance, backups, and Cloud SQL attachment/IAM. Do not expose an authorized network as a shortcut.
- **Cloud Tasks backlog:** inspect queue depth/age, finite delivery attempts, worker IAM/health, and outbox. Run the bounded outbox job only after the cause is understood.
- **Worker/provider failures:** query structured `generation_task_failed` counts and safe error codes. Never log provider raw responses, prompts, or base64.
- **GCS signing failure:** verify API `signBlob` on the dedicated signer and signer object-read access. Do not grant API Storage Admin.
- **Stale RUNNING accumulation:** run the stale-recovery job after confirming the threshold; it marks stale runs failed and never invokes the provider.
- **Asset reconciliation conflicts:** run reconciliation with metadata-read authority and inspect summary counts; it neither downloads bodies nor deletes objects.
- **Orphan cleanup conflicts:** run dry-run/operator inspection first. Scheduled `--apply` remains restricted to failed runs, retention, reference protection, object age, and generation preconditions. Cleanup alone has delete authority.

## Secret rotation

- **OpenAI:** add a new Secret Manager version, deploy or restart only the worker so it reads `latest`, verify one generation, then disable the old version.
- **Google Generative Language:** when enabled, rotate
  `jewelai-production-google-generative-language-api-key` the same way; verify one bounded
  preproduction generation before disabling the old version.
- **Database password:** create a temporary/new DB credential and Secret Manager version, roll all SQL consumers, confirm connections, then retire the old credential. Coordinate Terraform state/user ownership; never expose either password.
- **Auth0 Terraform M2M:** rotate in Auth0, update the protected GitHub Environment secret, validate a plan, then revoke the old secret. These credentials never enter GCP application runtime.

## Disaster recovery

- Restore Cloud SQL using an appropriate backup/PITR point after validating data loss implications. No untested RPO/RTO is claimed.
- Recover Terraform state from GCS object versions using an authorized operator; the bucket is versioned and non-public.
- Recover application images by immutable Artifact Registry digest.
- Recreate stateless Cloud Run services/jobs from Terraform after state and data dependencies are sound.
- Treat private GCS Assets independently from PostgreSQL metadata; use reconciliation after database recovery and never bulk-delete as repair.
