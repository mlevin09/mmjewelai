# ADR 0019: Authenticated reference Asset upload

Status: Accepted for Authenticated Reference Asset Upload HTTP Boundary v1. Date: 2026-09-27.

## Context

The provider-neutral Asset model and ingestion lifecycle already support reference images, and the
production GCS adapter provides create-only private writes. OIDC authentication, current database
organization membership, scoped sessions, metadata-only Asset responses, and authenticated signed
read access also exist. An authenticated frontend still lacks an HTTP transport for attaching a
reference photo, sketch, or inspiration image to a session. Generated Assets remain exclusively
worker-owned.

## Decision

Add `POST /sessions/{session_id}/assets` as an authenticated `multipart/form-data` action accepting
exactly one `file`. The existing bearer dependency and current database membership authorize the
selected `X-Organization-ID`; the scoped persisted session supplies the project. The server creates
the Asset UUID and always constructs `AssetIngestionRequest(kind=REFERENCE)` with no generation or
parent lineage. Caller filenames and multipart headers are untrusted, do not influence identity or
storage lineage, and are not persisted.

Accept only declared PNG, JPEG, and WebP media types, then require the existing bounded binary
signature validation to agree. The route reads fixed-size chunks and accumulates at most the
configured maximum plus one byte. `ASSET_UPLOAD_MAX_BYTES` defaults to 20 MiB and is startup-validated
from 1 byte through 100 MiB. Oversized content is rejected before Asset metadata or storage; invalid
and empty supported-media payloads are rejected before either as well.

Transport parsing stays in FastAPI. `RuntimeService` owns scoped session lookup, server ID creation,
the provider-neutral ingestion request, and safe response mapping. `packages/assets` remains
authoritative for signatures, hashing, canonical object keys, storage orchestration, and lifecycle.
The API receives only `PrivateObjectStore`; production composes the existing
`GcsPrivateObjectStore` from the same configured private bucket and ADC/workload identity. Writes
remain create-only. Successful requests return the existing storage-redacted `AssetResponse`; a
temporary signed read remains a separate `POST .../access` action.

Every successful POST creates a new Asset. There is no general idempotency-key contract. Storage
failures and conflicts map to a redacted 503; existing failed metadata may remain for operations.

## Alternatives rejected

- Public upload buckets, browser GCS credentials, signed PUT/POST, or resumable upload URLs.
- Client-selected Asset IDs, object keys, kind, tenant, project, hashes, sizes, or lineage.
- Generated Asset creation through the API.
- Filename-based MIME detection or base64 JSON payloads.
- Unbounded reads, batch/multiple-file upload, or a general idempotency framework.
- Image decoding, EXIF/ICC extraction, thumbnails, transformations, or antivirus infrastructure.
- Message-attachment tables, parser/design mutation, prompt compilation, or generation triggers.

## Consequences

Authenticated owner, admin, and member principals can attach one private reference image to a
session and later request the existing short-lived read capability. The binary passes through the
API in bounded memory before a private create-only write. The API runtime therefore needs narrowly
scoped private bucket object-create permission and metadata-read permission for the create-only
conflict path, plus its existing signed-read signing permissions; Storage Admin, Editor, and Owner
are unnecessary.

Repeated POSTs create distinct reference Assets. A crash after the durable write but before READY
may leave exact PENDING reference metadata. Automated reference-PENDING reconciliation and general
reference retention remain future work. Direct-to-GCS upload may be reconsidered only if measured
larger-file needs justify its additional capability design.

## Validation

API tests cover all supported media, signature mismatch, missing/unsupported MIME, empty and bounded
size behavior, filename irrelevance, authentication and all membership roles, revocation and tenant
scope, server project/UUID ownership, safe storage failures, list/get/signed-read integration, no
revision/message/prompt/generation side effects, OpenAPI, settings, and production composition
without GCP network access. Existing Asset/GCS, PostgreSQL, Alembic, lint, formatting, and schema
drift suites remain required. No migration or Asset schema version change is introduced.
