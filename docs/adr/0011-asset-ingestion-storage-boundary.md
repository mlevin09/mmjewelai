# ADR 0011: Private asset ingestion and storage boundary

Status: Accepted for Asset Ingestion + Storage Boundary v1. Date: 2026-09-24.

## Context

Generation results contain external provider metadata, not JewelAI-owned binaries. Durable reference
and generated images need private object storage, integrity metadata, tenant lineage, and retry-safe
lifecycle state. PostgreSQL is not appropriate binary storage. GCS remains the production target,
while cloud infrastructure and the provider-output transport are not yet implemented.

## Decision

Add `packages/assets`, depending only on Pydantic and the standard library. It defines immutable Asset
contracts, a create-only `PrivateObjectStore` port, bounded PNG/JPEG/WebP signature validation,
server-computed SHA-256 and size, server-generated tenant/project/asset keys, and one-shot ingestion.

Persist metadata through Alembic `0005_assets`. Ingestion writes `pending` metadata before the object,
then transitions to terminal `ready` or typed `failed`. PostgreSQL and object storage are explicitly
not a distributed transaction; pending rows make a post-write database failure observable and later
reconcilable. Same-ID/same-content retries are idempotent; changed content or lineage conflicts.

Generated assets anchor to one succeeded immutable GenerationRun output. A unique run/ordinal pair
has at most one canonical asset. Parent assets must share organization, project, and session. Public
responses omit object keys. No public/signed URL, binary API, provider fetch, or DesignRevision update
is part of ingestion.

## Alternatives

Binary PostgreSQL columns were rejected because metadata and large-object lifecycles differ. Provider
URLs were rejected because they are not owned durable assets. Public buckets were rejected. Coupling
the persistence package directly to a GCS SDK was rejected because it would bind contract and tests to
one infrastructure adapter before credentials, deployment, and access policy exist.

## Consequences

A future GCS adapter can implement the stable private storage port. Crashes may leave pending rows and
will require a future reconciliation job. Signed downloads, upload transport, retention/deletion,
transformations, EXIF handling, full image decoding/security analysis, and provider-output retrieval
remain separate decisions. The v1 signature check identifies supported formats but is not a complete
image decoder or malware analysis system.
