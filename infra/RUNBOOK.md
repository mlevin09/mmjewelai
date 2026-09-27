# JewelAI production runbook

Production operations are manual, reviewed, and credential-safe. Never paste tokens, signed URLs, database URLs, provider responses, prompts, or secret values into terminals recorded for issues or pull requests.

## Initial bootstrap

1. Create or select a billed GCP project and choose one primary region.
2. Create or select an Auth0 tenant. Create a least-privilege Auth0 Management API machine-to-machine client for Terraform; the tenant/account itself is not Terraform-managed.
3. Copy `infra/terraform/bootstrap/terraform.tfvars.example` outside Git, review the plan, and apply the bootstrap stack with an authorized operator identity.
4. Configure the protected GitHub `production` Environment. Add non-secret project, region, registry, state bucket, WIF provider, deploy-service-account, domains, DNS zone, and Asset bucket variables. Add `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, and `AUTH0_CLIENT_SECRET` as protected secrets.
5. For the first deployment only, apply the production OpenAI Secret Manager metadata target after review, then seed a version without Terraform: `gcloud secrets versions add jewelai-production-openai-api-key --data-file=-`. Do not enter the value into tfvars or command history. The normal deploy preflights an enabled version.
6. Confirm the existing Cloud DNS zone/domain inputs, or plan to create both A records from the `load_balancer_ip` output when DNS management is disabled.
7. Dispatch `Deploy production` from `jewelai-v2`, enter its exact SHA, approve the protected environment, and review the Terraform plan/apply record.
8. Create the first controlled-alpha Auth0 database user administratively. Terraform never stores users or passwords.
9. Open the web URL, sign in, and create the first JewelAI organization. Auth0 establishes identity only; PostgreSQL membership remains authorization authority.

No local developer task should apply either stack or mutate Auth0, GCP, DNS, users, or secrets.

## Normal deploy

1. Verify Runtime API, Web, and Infrastructure checks are green on the exact `jewelai-v2` SHA.
2. Dispatch the protected workflow with that SHA. It authenticates through WIF, builds and pushes SHA-tagged images, resolves registry digests, and passes only `@sha256` references to Terraform.
3. Review the protected environment approval and Terraform plan. Confirm no unexpected IAM, DNS, data-destruction, or secret-version changes.
4. The workflow applies, executes the migration job, waits, then checks API `/health`, web `/health`, and Auth0 discovery.
5. Confirm migration output remains `0009_generation_asset_maint (head)` for this release, queue depth is healthy, worker request events appear, and real PKCE login succeeds.
6. Validate `/me`, organization selection, one bounded generation, and signed Asset display. Confirm the bearer token is the access token with the exact API audience—not the ID token.

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
- **Database password:** create a temporary/new DB credential and Secret Manager version, roll all SQL consumers, confirm connections, then retire the old credential. Coordinate Terraform state/user ownership; never expose either password.
- **Auth0 Terraform M2M:** rotate in Auth0, update the protected GitHub Environment secret, validate a plan, then revoke the old secret. These credentials never enter GCP application runtime.

## Disaster recovery

- Restore Cloud SQL using an appropriate backup/PITR point after validating data loss implications. No untested RPO/RTO is claimed.
- Recover Terraform state from GCS object versions using an authorized operator; the bucket is versioned and non-public.
- Recover application images by immutable Artifact Registry digest.
- Recreate stateless Cloud Run services/jobs from Terraform after state and data dependencies are sound.
- Treat private GCS Assets independently from PostgreSQL metadata; use reconciliation after database recovery and never bulk-delete as repair.
