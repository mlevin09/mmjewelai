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
A durable queue is required before generation deployment; Cloud Tasks versus Pub/Sub is an open ADR decision.
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
`packages/model_gateway` owns provider-neutral generation contracts, `workers/generation` owns the
one-shot generation unit of work, `packages/assets` owns private binary-ingestion contracts and the
object-storage port, `packages/persistence` owns SQLAlchemy/Alembic metadata storage, and
`apps/api` is the FastAPI runtime boundary:

```text
apps/
  api/
  web/
workers/
  generation/
packages/
  domain/
  parser/
  prompts/
  assets/
  persistence/
  model_gateway/
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
Root V1 packaging, Docker files and README are preserved and must be migrated explicitly rather than silently reinterpreted as V2. See [ADR 0006](docs/adr/0006-modular-monolith-repository-layout.md).

## Delivery order and unresolved decisions

1. Jewelry Design Schema.
2. Role Profiles and Domain Dictionary.
3. Question Catalog.
4. Rules Engine with deterministic offline acceptance cases.
5. Persistence/API, parser and prompt compiler; then assets/jobs, frontend and A/B.
See [backlog](docs/product/BACKLOG.md), [data model](docs/architecture/DATA_MODEL.md) and [specifications](specs/README.md).

Before runtime deployment resolve authentication/tenancy model, queue, supported jewelry families/locales, retention policy and experimental assignment unit.
Exact role question budgets, domain catalogs and manufacturing constraints require product/domain review.
The reference conversation mentions image/template attachments; they are not treated as authoritative machine-readable specifications in this baseline.
