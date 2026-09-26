# JewelAI persistence package

This V2 package keeps PostgreSQL/SQLAlchemy concerns outside `packages/domain`. It stores relational
ownership and revision lineage plus the complete validated `DesignRevision` JSON snapshot. Snapshots
are validated before writes and revalidated on reads.

The `0002_parser_messages` migration adds bounded user-message records for parser provenance. Message
lookups are scoped by session and organization ownership. Parser candidates and proposals are not
persisted here; accepted changes continue through immutable specification revisions and CAS.

The `0003_prompt_revisions` migration pins the prompt artifact on each session and adds immutable
prompt revisions. Relational version/text/hash metadata must match a revalidated `CompiledPrompt`
payload. Prompt creation locks and checks the scoped session row before insert so a compilation whose
source revision became stale cannot persist.

The `0004_generation_runs` migration adds immutable generation input/lineage and bounded lifecycle
metadata. Repository methods create pending runs, atomically claim pending→running with a conditional
update, and row-lock terminal running→succeeded/failed transitions. Prompt revisions are revalidated
on read and must belong to the same scoped session. Result payloads contain provider metadata only,
never image bytes or long-lived URLs.

The `0005_assets` migration adds private object metadata and reference/generated lineage only. Image
bytes remain behind the `PrivateObjectStore` port. Repository methods validate organization → project
→ session, parent scope, and exact succeeded GenerationRun output lineage. A unique run/ordinal pair
prevents duplicate canonical generated assets.

The `0006_auth_membership` migration adds principals keyed uniquely by `(issuer, subject)` and
organization memberships. API organization creation writes the organization and creator OWNER
membership atomically. Owner deletion/demotion locks the organization row before checking for
another owner. Existing organizations are not assigned owners automatically.

The `0007_generation_dispatch_outbox` migration adds one minimal durable dispatch intent per
API-created GenerationRun. Creation is atomic with the run; pending rows contain no task body or
secret and are marked published idempotently after deterministic Cloud Tasks publication.

The `0008_generation_recovery_retry` migration enforces attempt/parent consistency, one
direct retry child per parent, and an indexed stale scan. Recovery atomically marks only sufficiently
old RUNNING rows `FAILED(execution_stale)`. Explicit retry locks a FAILED parent and derives the exact
child request from persisted history while inserting child and outbox in one transaction.

The `0009_generation_asset_maint` migration adds internal nullable reconciliation and orphan-cleanup
completion timestamps plus bounded-scan indexes. Repository scans select only old SUCCEEDED or FAILED
runs in deterministic batches. Guarded updates can mark reconciliation only on SUCCEEDED runs and
cleanup only on FAILED runs. These timestamps are not exposed by the Model Gateway contract or API.

Revision writes use a conditional `UPDATE design_session ... WHERE current_revision_id = :expected`
inside the same transaction as the immutable revision insert. A zero-row update raises the typed
`StaleRevisionError`; no stale snapshot is committed.

Run the migration from the repository root:

```sh
DATABASE_URL=postgresql+psycopg://jewelai:jewelai@localhost:5432/jewelai \
  alembic -c packages/persistence/alembic.ini upgrade head
```

Authentication is established above this package. Repository methods retain explicit organization
scope and ownership joins as defense in depth; they do not interpret bearer tokens or authorize from
IDs alone.

Run one bounded recovery batch with only database configuration:

```sh
DATABASE_URL=postgresql+psycopg://... \
  python -m jewelai_persistence.recover_stale --stale-after-seconds 1800 --batch-size 100
```

`GENERATION_STALE_AFTER_SECONDS` defaults to 1800 and is bounded to 900–86400;
`GENERATION_RECOVERY_BATCH_SIZE` defaults to 100 and is bounded to 1–100.
