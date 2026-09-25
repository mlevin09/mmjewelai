# ADR 0013: OpenAI image provider output retrieval

Status: Accepted for OpenAI Image Provider + Provider Output Retrieval v1. Date: 2026-09-25.

## Context

JewelAI already has provider-neutral Model Gateway contracts, an immutable GenerationRun lifecycle,
generated Asset lineage, private Asset ingestion, and a production GCS adapter. No real generation
provider connected these boundaries. OpenAI GPT Image is the first provider; its dedicated Images
API returns generated image content as base64, so provider URL retrieval is unnecessary.

## Decision

Add `packages/model_gateway_openai`, depending inward on `packages/model_gateway`, as the only OpenAI
SDK boundary. Text-to-image v1 calls `client.images.generate` once with the exact immutable compiled
prompt, exact server-selected allowlisted model, bounded `output_count` as `n`, and PNG output. The
production client uses standard environment credentials, a bounded timeout, and `max_retries=0`.

Treat responses as untrusted. Require the exact output count, a non-empty `b64_json` for each output,
bounded encoded size, strict base64 decoding, and bounded decoded size. Do not fetch provider URLs.
Persist only the existing metadata-only `GenerationResult`. Add a separate provider-neutral
`GenerationExecution`/`RetrievedImageOutput` runtime envelope whose repr hides bytes and which is
excluded from JSON Schema and PostgreSQL.

The worker validates result/payload alignment and PNG signature before completing the run. It then
persists GenerationRun success and materializes each transient output through existing
`ingest_asset`. Generated IDs are UUIDv5 using the fixed JewelAI namespace and the name
`{generation_run_id}:{ordinal}`. Asset ingestion remains authoritative for hashes, canonical object
keys, lineage, lifecycle, and storage. The worker imports neither OpenAI nor GCS.

Generation success and Asset storage are separate lifecycles. Storage failure after valid provider
execution leaves the GenerationRun succeeded and the Asset failed. No automatic provider or worker
retry exists.

## Alternatives

Putting OpenAI in Model Gateway core, persisting base64 or bytes, storing provider URLs, invoking the
provider from FastAPI, adding a generic URL downloader, implementing Gemini simultaneously, enabling
hidden SDK retries, weakening generated-Asset lineage to accept running runs, database blob storage,
treating the provider response as the canonical Asset, and bundling a durable queue or reconciliation
worker were rejected.

## Consequences

An actual OpenAI generation can now become a JewelAI-owned private Asset through an injected object
store such as GCS. A deliberate crash window remains after GenerationRun success and before all Asset
rows/objects are materialized; deterministic IDs make future reconciliation possible, but repair is
deferred. Durable queue delivery, explicit retry lineage, authentication, signed-access HTTP,
reference-image input, visual QA, provider cost accounting, and a second provider remain future work.

## Validation

Deterministic fake-client tests cover exact request mapping, model allowlisting, disabled retries,
strict and bounded decoding, safe provider-error mapping, metadata/payload alignment, deterministic
Asset IDs, duplicate delivery, storage failure, malformed output, and a full persisted
PromptRevision-to-READY-Asset flow without network or credentials. Existing PostgreSQL concurrency,
Alembic, schema-drift, lint, and regression suites remain required in CI.
