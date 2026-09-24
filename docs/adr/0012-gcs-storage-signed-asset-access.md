# ADR 0012: GCS storage and signed Asset read access

Status: Accepted for Production GCS Storage Adapter + Signed Asset Access Boundary v1. Date:
2026-09-24.

## Context

Asset Boundary v1 defines a private create-only object-storage port and persists only Asset metadata.
Binary objects target Google Cloud Storage. Provider generation results remain metadata-only, and
future clients need temporary read access to private assets. Authentication and organization
membership are not yet implemented, so the current ownership-scoping header cannot safely authorize
issuance of bearer signed URLs.

## Decision

Add `packages/assets_gcs` as a provider-specific adapter depending inward on `packages/assets`. Use
the Google Cloud Storage SDK with Application Default Credentials/workload identity and an explicitly
configured existing bucket. Never provision buckets or mutate IAM/ACLs.
The runtime needs object-create and object-metadata-read permissions scoped to that bucket; signing
requires an intentionally configured Google-supported signing identity.

Create objects with `if_generation_match=0`. Store JewelAI SHA-256 in custom
`jewelai-sha256` metadata and preserve native content type. On a precondition conflict, read metadata
and accept only an exact name/type/size/hash match as an idempotent retry; otherwise fail without
overwriting or downloading content.

Add a separate provider-neutral Asset Access v1 contract. Only a validated `ready` Asset with its
canonical object key can be signed. Default TTL is five minutes and maximum TTL is fifteen minutes.
The GCS adapter produces V4 HTTPS `GET` signed URLs. Signed URLs are ephemeral bearer secrets: do not
persist, log, cache as durable state, or expose them through HTTP before authentication and
membership authorization exist. Credentials that implement `google.auth.credentials.Signing` use
the Storage SDK's local signing path without an unnecessary token refresh. Non-signing
workload/metadata ADC credentials use a refreshed short-lived OAuth token plus an explicitly
configured or credential-exposed, validated service-account email; passing both to the Storage SDK
selects its IAM `signBlob` signing path without private-key material. The explicit signing identity
takes precedence, and missing identity, token-refresh, IAM, or signing failures remain private and
fail closed.

## Alternatives

Putting the Google SDK in `packages/assets`, public buckets or object ACLs, database image bytes,
provider URLs as assets, long-lived URLs, repository/config service-account private keys, and an
unauthenticated signed-URL endpoint were rejected. Provider-output retrieval and durable queue
selection remain separate tasks rather than being bundled into this adapter.

## Consequences

A production storage and signing adapter now exists without coupling the Asset core to Google.
Keyless signing requires the Service Account Credentials API, permission for the runtime principal
to call `iam.serviceAccounts.signBlob` on the selected signing identity, and object-read permission
for that signing identity. The signing email is non-secret configuration; OAuth tokens remain
transient and private keys are neither configured nor stored.
Actual binary upload transport, provider-output retrieval, authenticated HTTP access, bucket/IAM
provisioning, reconciliation, retention, and deletion remain future work. Normal tests use injected
fakes and require neither credentials nor network access.

## Validation

Unit tests assert generation-precondition writes, integrity metadata, metadata-only idempotency,
safe conflicts/errors, private ACL behavior, existing-bucket use, V4 GET signing, HTTPS and TTL
bounds, local signing credentials without refresh, keyless IAM signing with refreshed ADC, safe
identity/token/IAM failures, READY/canonical-key enforcement, schema drift, and unchanged
metadata-only API behavior.
