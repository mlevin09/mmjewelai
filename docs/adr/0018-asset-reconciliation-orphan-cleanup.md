# ADR 0018: Generated Asset reconciliation and failed-run orphan cleanup

Status: Accepted for Asset Reconciliation + Orphan Cleanup v1. Date: 2026-09-26.

## Context

Provider outputs are durably staged at deterministic private keys before a GenerationRun becomes
SUCCEEDED, while Asset metadata is finalized afterward. A crash can therefore leave paid output
durable but missing or PENDING in PostgreSQL. Failed runs—including ambiguous executions classified
by ADR 0017—can instead leave unowned staged objects. Deterministic generated Asset IDs and keys make
bucket-wide discovery unnecessary.

The normal generation path intentionally has create-only storage authority. Giving that path delete
authority would increase the blast radius of an execution bug, while operational repair still needs
metadata evidence and narrowly controlled deletion.

## Decision

Keep `PrivateObjectStore` create-only. Add separate provider-neutral maintenance capabilities:
`PrivateObjectMetadataReader` performs exact-key metadata inspection, and
`PrivateObjectVersionDeleter` deletes only a named object version. `PrivateObjectMaintenance`
combines them only for cleanup composition. Reconciliation receives metadata-read authority only.
Cleanup receives metadata read plus version-conditional delete authority.

Inspection returns exact key, MIME type, JewelAI SHA-256, positive size, timezone-aware creation
time, and an opaque version token. GCS maps the token to `blob.generation`. Inspection never reads
object bodies or lists buckets. Deletion uses `if_generation_match`; absence is idempotent, while a
precondition mismatch is a conflict and leaves the replacement untouched.

SUCCEEDED runs older than a five-minute default grace are reconciled in bounded deterministic
batches. Expected IDs are the historical UUIDv5 IDs. Missing Asset rows inspect the finite PNG,
JPEG, and WebP canonical candidates; exactly one valid object may be adopted. Exact PENDING rows may
be completed. READY rows are verified without storage access. FAILED Assets, missing objects,
malformed metadata, and multiple candidates block completion. Only when every expected output is
READY is `assets_reconciled_at` recorded.

FAILED runs older than a seven-day default retention are eligible for orphan cleanup. Run age and
object creation age must both pass the cutoff. Any Asset row—regardless of status—protects the
ordinal. Exactly one candidate may be removed, using its inspected version token. Cleanup is dry-run
by default and requires `--apply`; only fully clean runs receive `orphan_cleanup_completed_at`.
Active and successful runs are never cleanup targets.

The two nullable progress timestamps are internal persistence fields, not Model Gateway or public
API fields. Maintenance changes neither GenerationRun lifecycle nor retry/prompt lineage. Commands
are one-shot and provider-free; scheduling and IAM provisioning remain deployment work.

## Alternatives rejected

Regenerating missing output, bucket or prefix listing, downloading and hashing image bodies, public
buckets, unconditional/prefix deletes, deleting SUCCEEDED output, immediate failed-run cleanup,
deleting Asset rows, adding orphan/reconciled statuses, persisting GCS generations, combining this
with customer retention, and granting the normal generation path delete authority were rejected.

## Consequences

Paid successful output can be recovered without another provider call, and old failed-run storage
can be reclaimed without risking referenced or replaced objects. Malformed or ambiguous storage
requires operator investigation. GCS metadata is trusted only inside the private least-privilege
maintenance boundary. General customer retention/deletion and cloud scheduling remain future work.

## Validation

Asset, GCS, persistence, worker, pipeline, and PostgreSQL tests cover metadata-only adoption,
PENDING completion, finite MIME discovery, successful-run and DB-reference protection, object-age
gates, dry-run behavior, generation-match deletion, version races, durable progress, and the absence
of object downloads, bucket listing, and provider calls.
