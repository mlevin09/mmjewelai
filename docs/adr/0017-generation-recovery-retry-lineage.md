# ADR 0017: Generation recovery and explicit retry lineage

Status: Accepted for Stale RUNNING Recovery + Explicit Generation Retry Lineage v1. Date: 2026-09-26.

## Context

Cloud Tasks now durably delivers each immutable GenerationRun and duplicate delivery is safe through
the atomic PENDING→RUNNING claim. A worker can still crash after claiming a run. The provider may or
may not have received that request, so a permanently RUNNING row is operationally unsafe and
reopening it could duplicate paid generation. The existing `attempt` and
`parent_generation_run_id` fields were reserved for explicit retry lineage.

## Decision

Classify a RUNNING run as stale when its server-owned `started_at` is at or before a conservative
server cutoff. A bounded one-shot persistence command atomically changes only matching RUNNING rows
to `FAILED(execution_stale)`. The default threshold is 1800 seconds and the accepted range is
900–86400 seconds. This is timeout-based abandoned-run classification, not proof that a worker died.
It never resets a run to PENDING, calls a provider, creates dispatch work, or creates a retry.

An authenticated explicit retry of a FAILED run creates a new PENDING GenerationRun. The child copies
the exact persisted prompt revision/hash, profile ID/version, provider, model, and configuration;
increments `attempt` by exactly one; and points to the immediate failed parent. The parent is locked,
one direct child per parent is database-enforced, and repeated or concurrent requests return that
same child. The child and its own dispatch outbox commit atomically before best-effort immediate Cloud
Tasks publication. Publication failure leaves the child and outbox durably pending.

Cloud Tasks redelivery is delivery retry and never changes `GenerationRun.attempt`. A stale recovery
and a live worker terminal write race through database conditions/locks: exactly one terminal change
wins and no terminal run can reopen.

## Alternatives rejected

RUNNING→PENDING reset, automatic stale retry, same-row retry mutation, current-profile substitution,
prompt recompilation, retry siblings, heartbeat/Redis leases, provider queries during recovery,
Cloud Tasks attempts as business attempts, and bundling Asset reconciliation or deletion were
rejected.

## Consequences

Abandoned executions become inspectable terminal failures and explicit retry chains are linear and
deterministic. A retry can still duplicate external work if the ambiguous old provider request
actually executed, but the new paid attempt has separate immutable lineage. Old failed runs may have
orphan private objects, and succeeded runs may still lack Asset metadata. Asset reconciliation and
orphan cleanup remain the next separate reliability task.

## Validation

Model, migration, repository, API, worker, and cross-package tests cover exact cutoff behavior,
bounded scans, atomic recovery, strict retry input, historical input reuse, one-child idempotency,
PostgreSQL retry and recovery races, old-task acknowledgement, outbox atomicity, and full regression
and schema-drift checks.
