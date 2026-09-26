# ADR 0015: Authenticated signed Asset HTTP access

Status: Accepted for Authenticated Signed Asset Access v1. Date: 2026-09-26.

## Context

JewelAI stores Asset bytes in private object storage and metadata in PostgreSQL. The provider-neutral
Asset Access contract and production GCS V4 signer already exist, and OIDC authentication plus
database-authoritative organization membership now protect product routes. The API previously
returned Asset metadata only, leaving authenticated clients unable to display READY images without
making storage public, exposing object keys, or proxying bytes through FastAPI.

## Decision

Add `POST /sessions/{session_id}/assets/{asset_id}/access`. Minting a bearer capability is an action,
not a cacheable resource. The route requires the existing bearer authentication dependency, current
database organization membership, and `X-Organization-ID` as a tenant selector only. All normal
owner, admin, and member roles may request access. Existing scoped persistence must resolve the exact
session and Asset before the signer is called, so foreign or mismatched resources return scoped 404.

Use the persisted canonical Asset object key and existing `issue_asset_read_access` policy. Only
READY Assets qualify. Callers may request only a strict integer TTL from 1 through 900 seconds; the
default is 300 seconds. They cannot select the bucket, object key, HTTP method, signing algorithm, or
signing identity. The API depends on the provider-neutral `PrivateObjectAccessSigner`; production
composition constructs the existing `GcsPrivateObjectAccessSigner` from explicit bucket, optional
project, and optional signing-service-account configuration. Credentials continue to come from ADC
or workload identity. No object-existence network preflight is performed.

Return the existing `SignedAssetReadAccess` JSON contract, not a redirect. Responses use
`Cache-Control: no-store, private` and `Pragma: no-cache`. The signed HTTPS GET URL is an ephemeral
bearer secret and is never persisted, logged, embedded in ordinary Asset metadata, or cached as
durable server state. Safe errors map non-ready Assets to 409 and signer/contract failures to 503
without exposing storage or credential details.

Membership is checked on every capability-minting request. Revocation therefore prevents future
issuance, but an already-issued URL remains independently usable until its short expiration. No
signed-URL revocation table is introduced.

## Alternatives rejected

- Public buckets, object ACL changes, permanent URLs, or exposing object keys.
- Proxying or streaming binary content through FastAPI.
- Persisting signed URLs or adding an access-token/revocation table.
- Anonymous access, JWT role authorization, or owner/admin-only image access.
- A cacheable GET endpoint, HTTP redirect, or custom signing implementation in the API.
- A GCS metadata read before every access request.

## Consequences

Authenticated organization members can display private READY images through short-lived direct GCS
capabilities. Asset list/get responses remain URL-free, PostgreSQL remains metadata-only, and no
migration is required. An issued URL cannot be revoked early through membership, so the five-minute
default and fifteen-minute maximum bound exposure. Binary upload, queues, retries, reconciliation,
rate limiting, access audit, frontend integration, and visual QA remain future work.

## Validation

API tests cover authentication, current membership and revocation, all normal membership roles,
tenant/session/Asset scoping, strict TTLs, READY-only policy, safe signer failures, response
redaction/cache headers, no persistence, OpenAPI, and production configuration without GCP network
access. Existing Asset/GCS, auth, runtime, PostgreSQL concurrency, migration, lint, format, and schema
drift suites remain required.
