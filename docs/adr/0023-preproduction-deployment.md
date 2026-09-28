# ADR 0023: Isolated preproduction deployment

- Status: Accepted
- Date: 2026-09-28

## Context

The Google Generative Language image adapter requires a controlled environment for operator smoke
testing before any production enablement. JewelAI already has a reviewed production topology and
exact-plan deployment controls. Creating a divergent, reduced-security preproduction topology would
make the smoke test less representative and introduce a second infrastructure design to maintain.

The target GCP project is exactly `mmjewellai-preprod`. Its Google Generative Language API key is
already stored in Secret Manager as `jewelai-preprod-google-generative-language-api-key`; Terraform
must reference that secret without importing its value or attempting to recreate its metadata.

## Decision

Mirror the existing production Terraform architecture in a distinct `infra/terraform/preprod` root
stack. Production configuration remains unchanged. Preproduction fixes its environment identity to
`preprod`, uses `jewelai-preprod` resource names, `JEWELAI_ENVIRONMENT=preprod`, a separate
`preprod/platform` Terraform backend prefix, a dedicated `preprod` GitHub Environment, and
redundant exact `mmjewellai-preprod` project validation in both Terraform and the workflow.
Its regional baseline is `europe-west1`, with the private Asset bucket in `EUROPE-WEST1`.

Provision the state bucket, regional Docker repository, repository-and-branch-bound WIF provider,
and keyless `jewelai-preprod-deployer` from a distinct `infra/terraform/preprod-bootstrap` root.
The production bootstrap remains unchanged and is never applied to the preproduction project. The
preproduction bootstrap uses neither Owner nor Editor and reserves, but does not create, the
deterministic Asset bucket name consumed by the main stack.

The manual `Deploy preprod` workflow preserves separate plan and apply jobs while both use the
single `preprod` GitHub Environment. That environment must have a deployment branch policy
restricted to `jewelai-v2`. Preproduction intentionally requires neither reviewers nor self-review
prevention so an agent can execute the full delivery lifecycle. Only redacted plan text is uploaded
to GitHub. The exact binary plan remains in the private state bucket, is
checksum/configuration/object-generation bound, and is applied without re-planning.

Preproduction enables the exact Google image-model allowlist
`gemini-3.1-flash-lite-image,gemini-3.1-flash-image,gemini-3-pro-image`. The worker receives it as
`GOOGLE_GENERATIVE_LANGUAGE_ALLOWED_MODELS` and reads the existing API-key secret as
`GOOGLE_GENERATIVE_LANGUAGE_API_KEY`. The secret value never enters Terraform, GitHub variables,
logs, plans, images, or repository files. Generation profiles remain explicit protected-environment
configuration and must include a Google profile whose model belongs to that allowlist.

Before the first deployment, replace the unprovisioned preproduction Auth0 dependency with Google
Cloud Identity Platform in the same `mmjewellai-preprod` project. Terraform enables email/password
authentication, registers one Firebase Web application, and authorizes the exact preproduction web
domain. The Web application uses the official Firebase SDK with session persistence and sends ID
tokens as bearer tokens. The API verifies the Google signature, project audience, secure-token
issuer, lifetime, authentication time, and subject. Identity Platform authenticates; PostgreSQL
membership remains authoritative for organization roles and access. Production keeps its existing
Auth0/OIDC path until a separate production identity decision.

The preproduction deployer receives Firebase Editor and Identity Toolkit Editor so the reviewed
stack can initialize the Firebase project, manage its Web application, and manage Identity Platform
configuration. These preproduction-only roles do not alter the production bootstrap identity.

## Alternatives rejected

- A smaller preproduction topology that omits production IAM, queue, storage, or durability controls.
- Sharing production Terraform state, GitHub Environments, domains, credentials, or GCP resources.
- Reusing the production root/state with runtime overrides, which weakens the isolation boundary.
- Recreating, importing, or reading the Google image-generation API-key value through Terraform.
- Requiring an external Auth0 tenant for preproduction before any Auth0 resources or users exist.
- Automatic deployment on merge or permitting feature-branch deployment.

## Consequences

Preproduction exercises the real architecture and provider composition without modifying or
deploying production. Its bootstrap, state, deployment identity, and resource namespaces are
isolated, and static invariants retain the security-critical parity requirements. Operators must
configure the single protected `preprod` GitHub Environment, its non-secret values, and an explicit
Google generation profile before manual deployment. Identity Platform's Firebase client
configuration is generated by Terraform and is not secret. OpenAI remains
independently optional in preproduction; when its allowlist is empty, its secret metadata, IAM
grant, worker configuration, and preflight are omitted.

No cloud resource is created by CI, accepting this ADR, or merging the implementation. Deployment is
a later explicit protected workflow dispatch from an exact `jewelai-v2` commit.
