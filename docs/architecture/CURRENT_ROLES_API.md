# Current Roles backend (EN MASTER)

ROLES-001; see ADR 0044. No merge/deployment or shared database cleanup is implied.

## Runtime contract

Authenticated reads:

- `GET /roles`: all active current definitions (21 after initial import).
- `GET /roles/{role_id}`: full definition, sources, maturity, aliases and row revision.
- `GET /roles/{role_id}/context`: human-role context, passport maturity and null conversation policy.
- `GET /ui/catalog`: the nine configured Studio selections, ordered in application configuration;
  each carries `role_id`, `name_ru`, nullable `name_en` and `revision`.

Existing `POST /projects/{project_id}/sessions` accepts those nine selections. Existing session,
text-intake, revision and question routes remain in place; no new conversation/state engine.
Other canonical roles are available for internal lookup, not selectable in this Studio pilot.
Unknown, historical merged RR IDs and the six retired IDs receive `422 invalid_role`.
Missing/corrupt catalog storage receives `503 role_catalog_unavailable`, without raw SQL/data.
Organization membership and session scope remain mandatory and independent of human profession.

## Import and updates

Migration `0021_roles_foundation` creates one new table, imports 21 current records and adds
an unvalidated FK preserving preexisting session rows. No destructive live cleanup is run.
The migration must run through the independently authorized deployment path, not app startup.

Explicit re-import: set server-side `DATABASE_URL`, then run
`python -m jewelai_persistence.roles`. It reads the shipped source seed, never Google Drive.
The importer may also be called with an explicitly supplied complete 21-record set. Sources
are hash-validated and malformed imports fail transactionally. Row locks serialize existing
record updates; revision increments only for actual definition changes. Identical re-imports
leave timestamps/revisions unchanged. This is an operator function, not a public write API.
There is no cached historical Role Definition or legacy JSON reader. Source files remain
under `data/roles/sources`; they are evidence/import inputs, not an alternate runtime catalog.

Draft passports/personas are imported intact with their original source hashes. No new English
labels or role-specific LLM policies have been fabricated. Preserve their unverified maturity
when consuming context; never treat human characteristics as authoritative system instructions.

## Verification limits

Local SQLite HTTP tests exercise selection, intake/continuation, CAS, fresh-app restoration,
tenant denial, source fidelity, update visibility, malformed-data rejection and idempotency.
They cannot qualify PostgreSQL ARRAY/JSONB, actual Alembic execution or FK validation. The
PostgreSQL test uses the existing fresh-container/cluster/job safety gate before any DDL.
No shared data was purged. Existing records with old IDs remain stored but are unsupported.
