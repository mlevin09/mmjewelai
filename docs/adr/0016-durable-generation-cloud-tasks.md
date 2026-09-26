# ADR 0016: Durable generation delivery with Cloud Tasks

Status: Accepted for Durable Generation Queue + Cloud Tasks Delivery Boundary v1. Date: 2026-09-26.

## Context

GenerationRun and its one-shot atomic worker claim already exist, and the API never invokes a provider
inline. PostgreSQL and a queue cannot share one transaction, so committing a run and then performing
an untracked enqueue has a lost-dispatch crash window. Generation is command delivery, not broadcast.

## Decision

Use Google Cloud Tasks with a PostgreSQL transactional `generation_dispatch_outbox`. The API creates
the PENDING run and its one outbox row atomically, then attempts post-commit publication. Failure
leaves durable pending work for bounded one-shot redrive.

Generation Task schema 1.0.0 contains only `generation_run_id`, `session_id`, and `organization_id`.
Trusted execution state is reloaded from PostgreSQL. The task ID is
`generation-{generation_run_id.hex}`; `AlreadyExists` is idempotent publication success. SDK retries
are disabled because the outbox is the retry source of truth.

Cloud Tasks sends an HTTPS POST with Google OIDC. The worker Cloud Run service is private and IAM
allows only the task-delivery service account to invoke it. Cloud Tasks headers and end-user JWTs are
not service authentication. The handler reuses `execute_generation_run_with_assets`; the existing
PENDING→RUNNING claim remains authoritative under at-least-once delivery. Safe business outcomes and
duplicates are acknowledged with 2xx and never reopen or increment a GenerationRun.

## Alternatives rejected

Inline execution, naive commit-then-enqueue, enqueue-before-durable intent, random task IDs, Pub/Sub,
Redis/Celery, polling GenerationRun, resetting RUNNING, automatic FAILED retry, prompt/binary task
payloads, end-user JWT service authentication, and a public worker were rejected.

## Consequences

Every API-accepted run has durable dispatch intent, though publication and delivery may duplicate.
Deployment must provision the queue, private worker, least-privilege IAM, finite retry/backoff and
rate/concurrency controls, plus bounded redrive invocation. Asset reconciliation and infrastructure
provisioning remain future work.

[ADR 0017](0017-generation-recovery-retry-lineage.md) now defines stale RUNNING classification and
explicit generation retry. Cloud Tasks redelivery remains delivery retry only; it never increments
`GenerationRun.attempt`.
