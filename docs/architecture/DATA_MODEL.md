# Planned data model and storage boundary

This remains the broader logical model. Persistence + API Foundation v1 physically implements only
organization, project, design_session, specification_revision, and question_event; see ADR 0007 and
the initial Alembic migration. Later rows in this table remain plans, not implemented claims.

| Entity | Scope / relationships |
| --- | --- |
| organization, membership | Tenant and authenticated membership; separate from conversational role |
| project | Belongs to one organization |
| design_session | Project, selected role, locale, conversation state and pinned artifact versions |
| message | Session, actor, content, timestamp; privacy/retention policy pending |
| specification_revision | Immutable session revision, parent revision, schema version and field state |
| question_event | Semantic question ID/version, rule/version, target, answer and decision explanation |
| prompt_revision | Specification revision, template/compiler versions and compiled text |
| generation_run | Prompt revision, provider/model, parameters, status, retry lineage, latency/cost |
| asset | Organization/project, object key, content type/hash/size, parent asset, owning run and lifecycle state |
| experiment_assignment / event | Stable assignment, variant, outcome and related run/spec revision |

Field state separates value origin (explicit/derived/assumed/unknown) from confirmation and lock.
Record source message or KB record/version, rule, timestamp and uncertainty where applicable.
A lock is independent of provenance. Unknown cannot silently become assumed; inferred values require traceable policy.
Concurrent state writes require revision checks. Jobs require idempotency and bounded retries before deployment.
All foreign-key ownership checks must prevent cross-tenant access.

Binary assets belong in GCS; PostgreSQL contains metadata and object identifiers, not image bytes or long-lived public URLs.
Local repository data/ contains non-sensitive versioned catalogs only.
