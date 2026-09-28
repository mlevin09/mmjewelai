# JewelAI V2 deployment infrastructure

The V2 production and preproduction platforms are defined by parallel reviewed Terraform root
stacks and dedicated container definitions. No infrastructure is created by validation or
pull-request CI.

## Topology

```text
Internet -> HTTPS load balancer -> web Cloud Run
Browser  -> HTTPS load balancer -> API Cloud Run -> Cloud SQL / private GCS / Cloud Tasks
Cloud Tasks -> private generation worker -> OpenAI or Google / private GCS / Cloud SQL
Cloud Scheduler -> private Cloud Run jobs -> bounded maintenance commands
```

Separate production and preproduction bootstrap roots create their own versioned private state
buckets, regional Artifact Registry repositories, exact-repository/exact-branch GitHub Workload
Identity Federation providers, and keyless deployers. The production stack creates Auth0 resources,
Cloud SQL PostgreSQL 16, the private Asset bucket, finite Cloud Tasks queue, isolated service
accounts, three Cloud Run services, five Cloud Run jobs, schedules, HTTPS load balancing, managed
TLS, optional Cloud DNS records, Cloud Armor, logging metric, dashboard, alerts, and uptime checks.

The `Deploy preprod` workflow instantiates that architecture in the exact `mmjewellai-preprod`
project with the `preprod/platform` state prefix and `jewelai-preprod` resource namespace. It uses
the existing `jewelai-preprod-google-generative-language-api-key` secret and enables the three
reviewed Google image models. It cannot target the production project or production GitHub
Environments.

The environment lifecycle is **Local development → Preprod → Production**. Preproduction uses one
protected GitHub Environment named `preprod`; Terraform plan and apply remain separate workflow
stages that both use that environment. Preproduction has no human-review or prevent-self-review
gate, while the exact branch, commit, project, plan, and deployment-branch-policy checks remain
mandatory. Production keeps its independent protection policy.

Runtime service identities are intentionally separate. Web has no Google API permission. API can connect to SQL, create/read Assets, enqueue only on its queue, read only `DATABASE_URL`, and call `signBlob` only on the signing identity. Worker can connect to SQL, create/read Assets, and read `DATABASE_URL`, `OPENAI_API_KEY`, plus the optional Google Generative Language API key when that provider is enabled. Reconciliation reads object metadata. Cleanup alone can delete objects. The task-delivery identity can only invoke the private worker; scheduler can only run the maintenance jobs.

## Directories

- `docker/`: multi-stage non-root API, worker, and static web images.
- `terraform/bootstrap/`: one-time state, registry, and WIF foundation.
- `terraform/preprod-bootstrap/`: isolated preproduction state, registry, WIF, and deployer foundation.
- `terraform/production/`: reusable production application platform.
- `terraform/preprod/`: isolated preproduction mirror fixed to `mmjewellai-preprod`.
- `.github/workflows/deploy-preprod.yml`: protected exact-plan preproduction instantiation.
- `RUNBOOK.md`: operator procedures, incidents, rotation, rollback, and recovery.

## Validation

```bash
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform/bootstrap init -backend=false
terraform -chdir=infra/terraform/bootstrap validate
terraform -chdir=infra/terraform/preprod-bootstrap init -backend=false
terraform -chdir=infra/terraform/preprod-bootstrap validate
terraform -chdir=infra/terraform/production init -backend=false
terraform -chdir=infra/terraform/production validate
terraform -chdir=infra/terraform/preprod init -backend=false
terraform -chdir=infra/terraform/preprod validate
python3 infra/terraform/check_invariants.py
docker build -f infra/docker/api.Dockerfile -t jewelai-api:local .
docker build -f infra/docker/worker.Dockerfile -t jewelai-worker:local .
docker build -f infra/docker/web.Dockerfile -t jewelai-web:local .
```

Never commit tfvars, plans, credentials, customer data, signed URLs, or service-account keys.
Pull-request CI performs validation and builds but never pushes images or applies Terraform.
Production and preproduction applies are separate manual protected WIF workflows using immutable
image digests.
