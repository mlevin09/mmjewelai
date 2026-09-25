# ADR 0007: Persistence and API runtime boundary

Status: Accepted for Persistence + API Foundation v1. Date: 2026-09-24.

## Context

The deterministic domain foundation is complete and deliberately has no framework or database
dependency. The first runtime slice needs durable tenant lineage, immutable revisions, transactional
stale-write protection, artifact pinning, and a narrow HTTP interface without changing the domain
contracts or repurposing the preserved V1 root package.

## Decision

Add `packages/persistence` for SQLAlchemy models, scoped repositories, and Alembic migrations. Add
`apps/api` for environment configuration, explicit artifact loading, application services, HTTP
contracts, routes, and the FastAPI app factory. Dependencies point inward: API → persistence/domain;
persistence → domain; domain imports neither runtime package.

Persist organization, project, design session, specification revision, and question event only. Keep
the complete validated `DesignRevision` as JSON while retaining ownership, revision identity, parent,
number, schema version, and timestamps relationally. Validate snapshots before writes and after reads.

Use an atomic conditional update as compare-and-swap. In one transaction, update the session current
revision pointer only where it still equals `expected_revision_id`; a zero-row update raises
`StaleRevisionError`. Insert the immutable child revision only after winning that update, in the same
transaction. This makes a concurrent loser fail without committing a fork or overwriting history.

Load artifacts only from explicitly configured version paths. Persist every session's schema, role,
dictionary, question, and rules pins. A runtime that cannot supply those exact pins fails closed.

Use an explicit `X-Organization-ID` request scope until authentication is implemented. Repository
queries join session → project → organization. This is ownership plumbing, not an authentication
mechanism. Conversational Role Profiles never participate in access decisions.

## Dependencies and alternatives

FastAPI implements the accepted HTTP architecture; SQLAlchemy and Alembic implement the accepted
PostgreSQL persistence/migration architecture; Psycopg is the PostgreSQL driver; Uvicorn is the local
ASGI runner; HTTPX is test-only. Standard-library/Pydantic code cannot provide transactional SQL CAS,
migrations, an ASGI HTTP boundary, or PostgreSQL connectivity.

Row locks were considered, but conditional update CAS is smaller, avoids holding a read lock across
domain computation, and gives a direct affected-row conflict signal. Fully normalizing nested design
fields was rejected because it would duplicate and prematurely fragment the authoritative domain
contract. A database current-revision foreign key was deferred to avoid a circular insert dependency;
the repository transaction and immutable revision constraints maintain the pointer invariant.

## Consequences

SQLite supports fast portable behavior tests, but cannot prove PostgreSQL concurrency semantics. The
runtime CI job therefore runs migrations and the two-writer CAS test against PostgreSQL 16. Production
authentication, membership, retention, persistent KB lookup, parser, prompt compiler, providers,
assets, queues, and deployment remain unresolved and out of scope.

## Validation

Run the unchanged domain suite, runtime tests, PostgreSQL-marked concurrency test, Alembic upgrade,
Ruff lint/format checks, and schema/diff checks documented in the package READMEs and CI workflows.

The temporary unauthenticated `X-Organization-ID` API behavior is superseded by
[ADR 0014](0014-authentication-organization-membership.md). Its ownership-scoped repository checks
remain defense in depth beneath authenticated organization membership.
