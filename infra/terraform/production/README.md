# JewelAI production stack

This stack describes the reviewed production topology. It consumes the bootstrap-created remote state bucket, Artifact Registry, and GitHub deployment identity. It manages GCP runtime resources and resources inside an existing Auth0 tenant; it does not create the tenant, domain registration, users, secret values, or billing account.

## Prerequisites

- Bootstrap stack applied by an authorized operator.
- An existing Auth0 tenant and a least-privilege Management API machine-to-machine client.
- Existing Cloud DNS zone when `dns_managed_zone` is set.
- An enabled billing account and three immutable Artifact Registry image digests.
- A usable `OPENAI_API_KEY` Secret Manager version, seeded outside Terraform.

Auth0 provider authentication is supplied only through `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, and `AUTH0_CLIENT_SECRET` in the protected deployment environment. Do not put those values in tfvars.

## Validate without credentials

```bash
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform/production init -backend=false
terraform -chdir=infra/terraform/production validate
```

## Operator plan/apply

The backend bucket is intentionally selected at init time so the same configuration is reusable:

```bash
terraform -chdir=infra/terraform/production init \
  -backend-config="bucket=YOUR_STATE_BUCKET"
terraform -chdir=infra/terraform/production plan -var-file=production.tfvars
```

Use the protected `Deploy production` workflow for reviewed applies. Never commit `production.tfvars` or plan files.

## Guardrails

- API and web accept traffic only through the external load balancer. Worker invocation requires the Cloud Tasks identity.
- Cloud Run images must end in `@sha256:<digest>`.
- `(api_max_instances + worker_max_instances + five jobs) × (db_pool_size + db_max_overflow)` must leave at least ten connections below `database_max_connections` for operators.
- Defaults cap API at 5 instances, worker at 2 with concurrency 1, and queue dispatch at one request/second with five attempts.
- Cloud SQL defaults to `REGIONAL`, PostgreSQL 16, backups, PITR, deletion protection, and a 100 GiB storage growth cap.
- Asset storage is private, uniform-access, public-access-prevention enforced, and not versioned. No lifecycle deletes customer Assets.
- Only the cleanup identity can delete Asset objects. API and worker can only create/read.
- Terraform state contains the generated database password and must be treated as sensitive.
- No application service receives Auth0 management credentials. Web receives only public runtime configuration.
- A billing budget is not managed in v1 because billing-account IAM is organization-specific; operators should configure one separately without broadening the deployer.

See [../../RUNBOOK.md](../../RUNBOOK.md) for bootstrap, deployment, smoke, rollback, incident, rotation, and recovery procedures.

## Runtime configuration reference

Terraform assembles these values; this is documentation, not a `.env` file:

- API: secret `DATABASE_URL`; exact `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL`, `OIDC_ALLOWED_ALGORITHMS=RS256`; private bucket/signer; queue/location/worker URL/task identity; exact web origin; artifact pins; raw/Asset limits; and bounded DB pool settings.
- Worker: secrets `DATABASE_URL` and `OPENAI_API_KEY`; private bucket/project; server-side model allowlist; provider timeout; bounded DB pool settings.
- Web: the single non-secret `JEWELAI_WEB_CONFIG_JSON` object containing API URL, Auth0 authority/client ID, exact callback/logout URLs, `openid profile email`, and exact API audience.
- Jobs: only their necessary database secret plus queue or object-store settings. Reconciliation has read authority; cleanup alone has delete authority.

Google Application Default Credentials come from each Cloud Run service account. No runtime accepts a service-account key file.
