# ADR0041 — Non-destructive Design Session deletion

Status: Owner-approved contract (06 November 2026); implementation awaiting independent review.

## Context and decision

The Owner explicitly approved logical deletion with a tombstone, additive migration,
tenant-scoped DELETE, owner/admin authority, retained history/Assets, idempotent repeats
and an active-generation barrier. Physical cascades would violate existing immutable
completion/history and Asset lineage constraints and are not used.

`DELETE /sessions/{session_id}` returns204 after atomically recording `deleted_at` and
`deleted_by_principal_id` in the existing session metadata. The original actor/time are
preserved on repeat. Membership is checked under the existing organization-first lock
order and the session is locked before testing generation/setting the tombstone.
Wrong organization/nonexistent sessions return404; members without owner/admin authority
return403. Active runs and unfinished successful-result materialization return a safe409.

All public session-scoped routes reject a retired session; lists and scoped repository
queries exclude it. Generation creation/retry and primary session writers serialize on
the session row to prevent a new run after retirement. Canonical revisions, Messages,
enrichment cycles, completion bytes, prompts, outbox and Asset metadata/objects are retained.
Previously issued/in-flight short-lived Asset access keeps its existing expiry; new
requests for a retired session are rejected. No restore/purge API, provider action or storage deletion.

Migration0020 adds two nullable fields, a complete-pair CHECK and a RESTRICT actor FK.
Existing records remain active with NULL fields. Downgrade refuses to erase tombstones.
After retirement is used, rolling the application back to a version without lifecycle
guards could reopen those sessions; retain the guards as well as the data on rollback.
The normal reviewed preprod release must apply the migration before functional access
to the new runtime; no shared migration is executed during development.

## Alternatives and consequences

Physical cascade and browser-only removal are rejected. A second session store or
versioned application runtime is unnecessary. The list offers separate Delete/confirmation
controls only to owner/admin; backend authorization is authoritative. Acknowledged deletes
remove the exact scoped cache entry while failures leave the list intact.

Current ORM must not be executed against historical schema checkpoints. Migration tests
seed old columns through reflected Core inserts using current canonical factory data,
then verify source bytes and current HTTP reads after upgrade. Historical0018 CHECK
tests exercise that migration's actual upgrade/downgrade in isolation on the current
schema with real preparation artifacts; they do not claim a supported whole-head rollback
past0019. Existing disposable PostgreSQL identity/freshness guards remain unchanged.

The existing shared-dispatch/schema CI gate requires exact-head Full qualification.
This assignment prohibits Full Regression; no check is weakened or automatically bypassed.
Local focused results and any unexecuted PostgreSQL qualification must be disclosed;
independent acceptance, merge and live release remain separate gates.
