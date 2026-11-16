# ADR 0044 — One current PostgreSQL Roles catalog (EN MASTER)

Status: Owner-approved direction; implementation pending independent review. Date: 2026-11-16.

## Context

ROLES-001 replaces the six-role JSON runtime. Its scope explicitly excludes compatibility
with those historical sessions and does not authorize deleting shared data. The approved
Registry contains 21 canonical identities, nine draft passports and 36 draft proto-personas.

## Decision

Create one `roles` table, with the nine Owner-specified columns. Migration
`0021_roles_foundation` seeds complete source content. Explicit re-import is transactional:
identical records keep their revision; modified records increment it. PostgreSQL is the
operational source; normal startup never reads Drive or seeds a fallback catalog.

Runtime lookups read current rows rather than caching stale definitions. Old role artifact
fields retained in other wire/evidence contracts are opaque historical metadata: they do
not select a role catalog. Existing dictionary/question/rules/prompt pins remain enforced.

Studio selection and presentation order live in application configuration (nine defaults),
not database flags. All 21 identities remain available through authenticated read endpoints.
Professional identities never grant organization permissions. Draft passport/persona content
remains explicitly unverified source context, not executable conversation policy. No approved
role-specific conversation policy is imported. Shared questions reuse one EN/RU wording;
the existing sourced-with-uncertainty proposal mechanism applies uniformly, without automatic
acceptance, confirmation or LOCK bypass. There are no role-specific rule duplicates.

The session FK is added NOT VALID to preserve existing rows while enforcing new writes;
no shared records are purged. Old six-role IDs and merged RR aliases are not selectable.
Downgrade refuses to discard roles used by sessions or definitions updated after import.

## Alternatives and consequences

Rejected: dual catalogs, legacy aliases, role-version/history tables, automatic translation
and persona-to-system-prompt conversion. Current-role edits intentionally affect subsequent
context reads. Historical role definitions are not replayed. Full original source documents
and import hashes are retained; English labels remain null where no approved label exists.

Within an existing unit of work, current Roles use the same non-owning Session reader as
canonical history. Rules and Questions receive request-local bindings; global artifacts
are never rebound. Only the reader binding is cached, never definitions/revisions. This
avoids a second Session closing/rolling back the caller's SQLite StaticPool connection.
Role reads do not commit or roll back the caller's writes, including catalog-validation
failure. Standalone reads retain ordinary factory ownership; callers inside a transaction
must use its locked reader rather than opening an unrelated factory-bound registry.

No Studio UI, providers, Knowledge activation, shared migration execution or deployment
is included. PostgreSQL execution must pass the existing independent disposable-DB gate;
SQLite checks cannot qualify ARRAY/JSONB or the actual FK migration.
