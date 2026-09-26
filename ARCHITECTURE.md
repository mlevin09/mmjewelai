# JewelAI V2 architecture baseline

Status: accepted direction for foundation work; detailed contracts remain draft until their issues are implemented and reviewed.
Date: 2026-09-20. Source: product discussion "Создание промпта визуализации" and the repository preparation request.
This is a design baseline, not an implemented backend. See [repository audit](docs/architecture/REPOSITORY_AUDIT.md).

## Product and boundary

Build a reusable jewelry design intake and prompt orchestration core for six roles: retail_client, sales_manager, buyer, marketing, jewelry_designer, industrial_designer.
One canonical design state serves all roles. Roles change vocabulary, depth and question policy, not separate engines or authorization.
The eventual internet-accessible A/B MVP includes UI, authentication, API, durable jobs and image generation; those are later phases.

## Core flow

User request + role → parser proposal → schema validation → state update → deterministic gap/rules engine → semantic question ID → role/locale wording → answer.
When ready: sourced knowledge enrichment + disclosed assumptions → validation → immutable specification revision → prompt compiler → Model Gateway.
Provider output is an untrusted proposal. Enforce locked constraints in code before accepting updates and validate compiled prompts before generation.

## Component ownership

| Component | Responsibility |
| --- | --- |
| Jewelry Design Schema | Canonical fields, units, provenance, confirmation and independent lock status |
| Role Profiles | Terminology, detail level, allowed question/default policies |
| Domain Dictionary | Stable domain IDs, synonyms, translations; not question selection |
| Question Catalog | Semantic IDs, target fields, wording and answer contracts |
| Rules / Gap Engine | Missing-field detection, deterministic priorities, ask/derive/assume/block/ready decisions |
| Parser Proposal | Validates untrusted structured candidates and proposes explicit schema updates; never writes revisions |
| Limited knowledge base | Sourced estimates of gemstone geometry with uncertainty; never substitutes for exact measurements |
| Prompt compiler | Versioned templates and verifiable locked constraint inclusion |
| Model Gateway | Provider-neutral parsing/generation interfaces; OpenAI/Gemini adapters later |

## Target platform (not provisioned)

Python/FastAPI API; PostgreSQL with SQLAlchemy/Alembic for persistent state and lineage.
GCP Cloud Run for API/workers, Cloud SQL for PostgreSQL, Cloud Storage for binary assets.
Google Cloud Tasks is the durable generation command-delivery mechanism. PostgreSQL records a
transactional dispatch outbox before post-commit publication; see ADR 0016.
Secret Manager holds provider credentials; organization/project ownership must be enforced on all records and asset access.
Store source files privately and issue time-limited access URLs. A CDN is optional after measured demand.
Start analytics with PostgreSQL; introduce Parquet exports and pgvector only for demonstrated needs. No dedicated vector database or BigQuery requirement for foundation.
Deterministic specification/prompt validation is mandatory. Visual QA is sampled or conditional in the later image stage, not a paid blocking call for every A/B result.

## Versioning and experiments

Record schema, role, dictionary, question, rule, KB and prompt versions, spec revision, provider/model/configuration, timestamps and run lineage.
A/B assignment must be stable at a documented unit (user/project to be decided), with variant, latency, cost and outcome events. Do not mix policy/provider changes without tracking them.
Never mutate a historical spec revision or silently replace the artifacts referenced by a generation.

## Repository layout

Existing root files are retained as V1. Foundation contracts live in `specs/`, reviewed catalogs in `data/`, and decisions in `docs/adr/`.
Step 2 established the modular-monolith skeleton below. `packages/domain` contains deterministic
behavior, `packages/parser` owns the provider-neutral candidate/proposal boundary,
`packages/prompts` owns deterministic provider-neutral prompt compilation and lock verification,
`packages/model_gateway` owns provider-neutral persisted and transient generation contracts,
`packages/model_gateway_openai` translates those contracts to the production OpenAI Images API,
`workers/generation` owns the one-shot generation and generated-Asset materialization unit of work,
`packages/assets` owns private binary-ingestion and temporary
read-access contracts, `packages/assets_gcs` implements the production Google Cloud storage/signing
adapter, `packages/auth` owns provider-neutral identity and membership policy,
`packages/auth_oidc` verifies configured asymmetric OIDC JWTs, `packages/persistence` owns
SQLAlchemy/Alembic metadata storage, and
`apps/api` is the FastAPI runtime boundary:

```text
apps/
  api/
  web/
workers/
  generation/
packages/
  auth/
  auth_oidc/
  domain/
  parser/
  prompts/
  assets/
  assets_gcs/
  generation_queue/
  generation_queue_gcp/
  persistence/
  model_gateway/
  model_gateway_openai/
data/
specs/
docs/
infra/
tests/
```

Applications and workers may depend on reusable packages; reusable packages must not depend on
applications or workers. `packages/parser` depends only on the domain contract and Pydantic;
`packages/prompts` has the same inward-only dependency boundary. `packages/domain` remains
independent of parser, prompts, Model Gateway, FastAPI, and SQLAlchemy. Generation is anchored to an
immutable prompt revision; API creation never invokes a provider inline. See
[ADR 0007](docs/adr/0007-persistence-api-runtime-boundary.md) for runtime persistence and CAS and
[ADR 0008](docs/adr/0008-parser-proposal-boundary.md) for candidate trust and proposal acceptance.
See [ADR 0010](docs/adr/0010-model-gateway-generation-boundary.md) for generation lifecycle,
atomic claim, and provider-result trust.
See [ADR 0011](docs/adr/0011-asset-ingestion-storage-boundary.md) for private object ingestion,
metadata lifecycle, and cross-system retry semantics.
See [ADR 0012](docs/adr/0012-gcs-storage-signed-asset-access.md) for create-only GCS writes and the
provider-neutral signed-read boundary. No signed-access HTTP route exists before authentication.
See [ADR 0013](docs/adr/0013-openai-image-provider-output-retrieval.md) for isolated OpenAI Images API
translation, transient base64 retrieval, and GenerationRun-to-Asset materialization.
See [ADR 0014](docs/adr/0014-authentication-organization-membership.md) for bearer identity,
database-authoritative organization membership, and final-owner protection.
See [ADR 0015](docs/adr/0015-authenticated-signed-asset-http-access.md) for authenticated,
session-scoped issuance of short-lived private Asset read capabilities without exposing object keys
or proxying bytes.
See [ADR 0016](docs/adr/0016-durable-generation-cloud-tasks.md) for transactional generation
dispatch, deterministic Cloud Task identity, and private IAM-authenticated worker delivery.
See [ADR 0017](docs/adr/0017-generation-recovery-retry-lineage.md) for bounded stale RUNNING
classification and exact-input explicit retry children.
See [ADR 0018](docs/adr/0018-asset-reconciliation-orphan-cleanup.md) for metadata-only adoption of
durable successful output and delayed version-conditional cleanup of failed-run orphan objects.
Root V1 packaging, Docker files and README are preserved and must be migrated explicitly rather than silently reinterpreted as V2. See [ADR 0006](docs/adr/0006-modular-monolith-repository-layout.md).

## Delivery order and unresolved decisions

1. Jewelry Design Schema.
2. Role Profiles and Domain Dictionary.
3. Question Catalog.
4. Rules Engine with deterministic offline acceptance cases.
5. Persistence/API, parser and prompt compiler; then assets/jobs, frontend and A/B.
See [backlog](docs/product/BACKLOG.md), [data model](docs/architecture/DATA_MODEL.md) and [specifications](specs/README.md).

Before runtime deployment resolve identity-provider provisioning, queue, supported jewelry
families/locales, retention policy and experimental assignment unit.
Exact role question budgets, domain catalogs and manufacturing constraints require product/domain review.
The reference conversation mentions image/template attachments; they are not treated as authoritative machine-readable specifications in this baseline.

Generation delivery and business retry are separate flows. Cloud Tasks delivers one immutable run;
an atomic worker claim leads to one terminal outcome. A bounded recovery operation changes an old
RUNNING row only to `FAILED(execution_stale)`. A later explicit retry creates a new GenerationRun and
outbox using the exact historical request; no stale run is reset or automatically regenerated.

Generated output follows provider → create-only durable object staging → SUCCEEDED → Asset metadata
finalization. A separate metadata-read-only reconciliation path repairs incomplete successful Asset
metadata. Failed-run cleanup is a distinct operator capability: after a seven-day default grace it
may delete only an unreferenced exact object version. Neither maintenance path downloads image bytes,
lists the bucket, invokes a provider, or changes GenerationRun status or lineage.
