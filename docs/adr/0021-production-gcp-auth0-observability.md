# ADR 0021: Production GCP, Auth0, and observability

- Status: Accepted
- Date: 2026-09-27

## Context

JewelAI now has an end-to-end browser, API, durable generation, private Asset, and maintenance workflow. Production infrastructure has not been provisioned. The application has provider-neutral OIDC contracts and bounded operational commands, but real identity provisioning, deployment credentials, runtime isolation, and operational telemetry are not yet expressed as a reproducible platform.

## Decision

Production is described with bounded Terraform stacks on GCP. A small bootstrap stack owns the private versioned state bucket, regional Artifact Registry, and GitHub Actions WIF identity. The production stack owns Cloud Run services/jobs, Cloud SQL PostgreSQL, private GCS, Cloud Tasks, Secret Manager metadata, external HTTPS load balancing, Cloud DNS records when enabled, Google-managed TLS, isolated user-managed service accounts, and Cloud Monitoring/Logging resources.

The web and API are reached only through the load balancer; the worker is private and callable only by the task-delivery identity. Scheduled maintenance uses private Cloud Run Jobs and a dedicated scheduler identity. Runtime identities have distinct SQL, queue, storage, signing, and secret permissions; only cleanup can delete Asset objects. Production images are immutable digests. Deployment is a manually dispatched, protected GitHub Environment workflow using WIF, never a service-account JSON key.

Auth0 is the concrete production OIDC provider. Terraform manages an RS256 API Resource Server, SPA client with exact HTTPS callbacks/origins, and controlled database connection inside an existing tenant. The browser remains an Authorization Code + PKCE public client without a secret and sends the exact configured API audience. Auth0 establishes external identity only; JewelAI PostgreSQL membership remains authoritative for owner/admin/member authorization.

The web receives validated non-secret runtime configuration at container startup. API and worker emit bounded structured JSON events with server-generated request IDs and safe identifiers. Cloud Monitoring supplies dashboard, alerts, uptime checks, and a log-based generation-failure counter. A raw ASGI body limit protects request parsing independently from the Asset domain limit. Production applies remain separate operator actions.

## Alternatives rejected

- Long-lived service-account JSON in GitHub or the default Compute Engine service account.
- Public worker/jobs, wildcard Auth0 callbacks/CORS, Auth0 roles/organizations as JewelAI authorization, or an Auth0/browser/OpenAI secret in web code.
- Mutable `latest` deployment, public GCS, broad Storage Admin runtime roles, or delete authority in the normal API/worker.
- Unlimited Cloud Tasks retries, automatic deployment on every merge, credentials in tfvars, or a Vite development server in production.
- Browser `localStorage` access tokens or raw logs containing user input, tokens, provider data, signed URLs, prompts, or image bytes.

## Consequences

Production deployment becomes reproducible, inspectable, manually approved, and reusable for a later staging environment. Runtime identities and maintenance authority are isolated, and operators gain health, latency, backlog, SQL, and business-failure telemetry. The Auth0 tenant, real domains/DNS, Management API credentials, production secret values, billing, and an authorized initial bootstrap remain operator prerequisites. Terraform state contains generated sensitive database material and must remain encrypted, versioned, non-public, and tightly controlled. No cloud resource is created by accepting this ADR or running pull-request validation.

## Validation

CI formats/validates both stacks without credentials, runs focused IAM/storage/queue invariants, and builds all production images. Runtime/API and web workflows verify the application changes. The deploy workflow is manual, branch/SHA gated, WIF-authenticated, and digest-based. Both plan and apply environments require production protection because both receive privileged credentials. The exact binary plan remains a short-lived, checksum-bound object in the private state bucket; GitHub receives only the redacted review rendering. Apply never re-plans. Managed DNS uses bounded HTTPS-readiness polling; external DNS produces an explicit record handoff and defers required HTTPS smoke verification to a later operator-requested run.
