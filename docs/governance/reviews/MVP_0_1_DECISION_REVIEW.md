# Historical MVP 0/1 Decision Review

Status: Working review
Reviewed: 2026-09-27
Source: `JewelAI_MVP_0_1_Map_v1.0.xlsx`

## Purpose

Review the historical MVP spreadsheet without treating its decision column as current product strategy.

The workbook contains **87 populated decision cells**:

- 71 — `Включить в MVP-0`
- 12 — `Включить в MVP-1`
- 3 — `Убрать`
- 1 — `Оставить как есть`

These cells are historical planning evidence. They are **not migrated automatically** into the current Project Decision Log.

The workbook reflects an earlier Retail/MVP framing and an earlier implementation generation. Current JewelAI product prioritization is open, and current V2 repository architecture may supersede earlier implementation assumptions.

## Review rule

For every historical row:

1. preserve the original decision as historical evidence;
2. do not convert MVP-0/MVP-1 ordering into current priority;
3. compare implementation assumptions with current repository/ADRs where relevant;
4. treat product-feature choices as unresolved unless there is a newer explicit team decision;
5. migrate only a durable current decision that is explicitly confirmed through the current decision process.

## Explicit rows whose source was itself labeled "Решение"

The workbook contains six rows where the source column is explicitly `Решение`.

| Excel row | Historical item | Historical decision | Current review |
|---|---|---|---|
| 17 | Галерея примеров / инспирация | Оставить как есть / не планировать | Historical product choice. No current cross-ecosystem prohibition established. Do not migrate. |
| 27 | Интеграция с amoCRM / 1С | Включить в MVP-1 | Historical sequencing. No current product priority established. Do not migrate. |
| 68 | Multi-tenancy (несколько салонов) | Включить в MVP-1; separate deployment considered acceptable | **Implementation assumption superseded in V2.** Current repository ADR 0014 uses authenticated organization membership as an authorization/tenant boundary. Do not migrate the old separate-deployment assumption. |
| 94 | Деплой: отдельный HTML для каждого салона | Включить в MVP-0 | **Superseded as a current implementation assumption.** V2 uses a shared web/API platform with organization membership and production platform infrastructure. Keep only as historical pilot context. |
| 101 | Психотипы клиентов и адаптивный UX | Убрать | Historical product choice. No current ecosystem-wide prohibition established. Do not migrate. |
| 102 | Давление на депозит как отдельный сценарий | Включить в MVP-0, despite earlier "не планируем" proposal | Internally conflicting historical row. The comment reframes the need as deposit/payment-state tracking in the funnel. Treat as unresolved product hypothesis, not a current decision. |

## Material implementation assumptions from the workbook

### localStorage as storage

Historical row: localStorage retained only as UI draft/not source of truth.

Current V2 direction is consistent with moving authoritative state to backend persistence. Repository architecture and ADR 0003 define PostgreSQL/SQLAlchemy/Alembic for persistent metadata and GCS for binary assets.

**Review:** historical row is directionally superseded by implemented V2 persistence architecture; do not create a new Project decision merely to restate current repository architecture.

### Server-side storage

Historical row called for server-side storage of showcases, events and approval documents.

Current V2 repository has backend persistence foundations and explicit storage/asset boundaries.

**Review:** historical product data model should not be copied verbatim; current schemas/contracts govern implementation.

### Multi-user / organization access

Historical rows proposed one manager, director visibility, manager-level separation, and later multi-tenancy.

Current V2 repository contains authentication and organization membership with owner/admin/member authorization in ADR 0014.

**Review:** earlier role/access assumptions are superseded where they conflict with current implementation. Conversational/professional roles remain distinct from authorization roles.

### Deployment model

Historical workbook treated one HTML deployment per salon as acceptable for early scale.

Current V2 production architecture is a shared Cloud Run/Auth0/PostgreSQL/GCS platform described by ADR 0021 and related infrastructure.

**Review:** old per-salon HTML deployment is historical only.

## Product-feature decisions

The remaining historical decision cells — including consultation/visualization, CRM fields, showcase behavior, pipeline steps, documents, analytics, pricing/calculators, stone-supplier features, Telegram, and manager UX — are retained as **historical product-planning evidence**.

They must not be interpreted as:

- current JewelAI ecosystem scope;
- current MVP-0/MVP-1 sequencing;
- proof that Retail is the first product;
- approved requirements;
- current implementation state.

Where a feature is relevant to a new product decision, re-evaluate it against current user evidence, product scope, technical feasibility, shared-core implications, and present constraints.

## Outcome

No historical MVP spreadsheet row is migrated into `DECISION_LOG.md` as an Accepted Project decision.

Two earlier implementation assumptions are explicitly treated as superseded by current V2 repository architecture:

1. separate per-salon HTML deployment as the intended scaling model;
2. delayed/implicit tenant boundary in place of current authenticated organization membership.

All other feature-level decisions remain historical evidence or unresolved hypotheses until explicitly revisited.

## References

- `ARCHITECTURE.md`
- `docs/adr/0003-backend-storage.md`
- `docs/adr/0014-authentication-organization-membership.md`
- `docs/adr/0021-production-gcp-auth0-observability.md`
- `docs/governance/DECISION_LOG.md`
- `docs/governance/SOURCE_MAP.md`
