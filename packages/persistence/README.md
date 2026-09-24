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

Revision writes use a conditional `UPDATE design_session ... WHERE current_revision_id = :expected`
inside the same transaction as the immutable revision insert. A zero-row update raises the typed
`StaleRevisionError`; no stale snapshot is committed.

Run the migration from the repository root:

```sh
DATABASE_URL=postgresql+psycopg://jewelai:jewelai@localhost:5432/jewelai \
  alembic -c packages/persistence/alembic.ini upgrade head
```

Authentication is not implemented. Repository methods require an explicit organization scope and
join through project ownership so a future authenticated organization context can be supplied.
