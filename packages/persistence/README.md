# JewelAI persistence package

This V2 package keeps PostgreSQL/SQLAlchemy concerns outside `packages/domain`. It stores relational
ownership and revision lineage plus the complete validated `DesignRevision` JSON snapshot. Snapshots
are validated before writes and revalidated on reads.

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
