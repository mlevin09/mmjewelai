# ADR 0010: Provider-neutral Model Gateway and generation-run boundary

Status: Accepted for Model Gateway + Generation Run Boundary v1. Date: 2026-09-24.

## Context

An immutable validated prompt revision must be executable later without allowing provider behavior to
alter canonical design or prompt state. Provider latency and duplicate delivery make inline HTTP
generation unsafe, while durable queue and asset-storage choices remain unresolved.

## Decision

Add `packages/model_gateway`, depending only on Pydantic and prompt contracts. It defines bounded
request, result, output-descriptor, lifecycle, error, and synchronous gateway protocol contracts.
Requests contain the exact `CompiledPrompt`; adapter results are untrusted and must match run,
provider, model, requested output count, ordinals, and bounded identifiers. No binary or URL is an
asset, and no provider implementation is included.

Persist immutable generation input and lineage through Alembic `0004_generation_runs`. States are
pending, running, succeeded, and failed. A conditional SQL update atomically claims pending→running;
terminal transitions lock the running row and cannot reopen a terminal run. Attempt is 1 and optional
parent lineage is reserved for future explicit retries; there is no automatic retry loop.

The API resolves a trusted injected versioned generation profile and creates a pending run only. It
does not accept provider configuration or call a gateway. `workers/generation` provides one explicit
unit of work: claim, load the exact prompt revision, construct a request, invoke an injected adapter,
validate output, and persist a typed result or safe failure. Duplicate delivery cannot invoke an
adapter after a run is claimed or terminal. A newer current design revision is irrelevant.

## Alternatives

Inline API execution was rejected because provider latency and retry behavior do not fit an HTTP
lifecycle. Arbitrary provider/configuration dictionaries were rejected in favor of server-controlled
profiles. Dynamic adapter imports and a plugin framework were rejected as unnecessary. Persisting
image bytes, base64, or provider URLs was rejected because future JewelAI-owned assets belong in GCS.

## Consequences

The boundary proves contract validation, lineage, state transitions, atomic PostgreSQL claim, and
duplicate-delivery safety. It does not prove visual quality or pixel-level lock compliance. Real
providers, credentials, bounded network timeouts, durable queue choice, retries, asset ingestion/GCS,
visual QA, authentication, and deployment remain deferred.
