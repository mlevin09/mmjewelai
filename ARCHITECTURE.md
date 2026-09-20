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

Existing root files are retained as V1. Foundation contracts live in specs/, reviewed catalogs in data/, and decisions in docs/adr/.
Future runtime layout: apps/api, apps/web, packages/domain, packages/prompts, packages/model_gateway, workers/generation, infra and tests.
Create runtime packages only in their implementation issues; root V1 packaging must be migrated explicitly.

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
