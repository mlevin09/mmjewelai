# JewelAI preproduction stack

This root stack mirrors the reviewed production topology while remaining isolated in the exact
`mmjewellai-preprod` project. It has its own `preprod/platform` GCS backend prefix,
`jewelai-preprod` resource names, GitHub Environments, domains, Auth0 resources, runtime identities,
database, queue, Asset bucket, and monitoring resources. It cannot target production.

Use only the protected `Deploy preprod` workflow from an exact `jewelai-v2` SHA. The workflow
requires both `preprod-plan` and `preprod` to have a deployment branch policy restricted to
`jewelai-v2`. Reviewer and prevent-self-review gates are intentionally not required for
preproduction. It stores only redacted plan text in GitHub; the exact binary plan is
kept temporarily in the private state bucket and applied without re-planning.

## Google provider

The stack requires this exact allowlist and passes it to the worker as
`GOOGLE_GENERATIVE_LANGUAGE_ALLOWED_MODELS`:

```text
gemini-3.1-flash-lite-image,gemini-3.1-flash-image,gemini-3-pro-image
```

It looks up the existing `jewelai-preprod-google-generative-language-api-key` Secret Manager
resource and mounts its latest enabled version as `GOOGLE_GENERATIVE_LANGUAGE_API_KEY`. Terraform
does not create the secret, read its value into state, or expose it in a plan. The protected
`GENERATION_PROFILES_JSON` configuration must contain at least one Google profile whose model is in
the exact allowlist. OpenAI configuration is independent and optional: leaving
`OPENAI_ALLOWED_MODELS` empty creates no OpenAI secret metadata or worker credential mount.

## Credential-free validation

```bash
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform/preprod init -backend=false
terraform -chdir=infra/terraform/preprod validate
python3 infra/terraform/check_invariants.py
```

No local validation command applies infrastructure. See [../../RUNBOOK.md](../../RUNBOOK.md) for
protected environment setup, deployment, DNS handoff, and the bounded provider smoke test.
