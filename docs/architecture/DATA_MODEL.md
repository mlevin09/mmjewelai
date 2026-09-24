# Planned data model and storage boundary

This remains the broader logical model. The runtime physically implements organization, project,
design_session, message, specification_revision, question_event, prompt_revision, generation_run,
and asset; see ADRs 0007–0011 and the Alembic migrations. Later rows remain plans, not implemented
claims.

| Entity | Scope / relationships |
| --- | --- |
| organization, membership | Tenant and authenticated membership; separate from conversational role |
| project | Belongs to one organization |
| design_session | Project, selected role, locale, conversation state and pinned artifact versions |
| message | Implemented user-message lineage: session, bounded content, server timestamp; privacy/retention policy pending |
| specification_revision | Immutable session revision, parent revision, schema version and field state |
| question_event | Semantic question ID/version, rule/version, target, answer and decision explanation |
| prompt_revision | Implemented immutable specification link, template/compiler versions, validated structured prompt, text and hash |
| generation_run | Implemented immutable prompt/profile/provider/config input, pending/running/succeeded/failed lifecycle, attempt/parent lineage and metadata-only result/error |
| asset | Implemented private metadata: organization/project/session, object key, type/hash/size, optional parent and generation-output lineage, pending/ready/failed lifecycle |
| experiment_assignment / event | Stable assignment, variant, outcome and related run/spec revision |

Field state separates value origin (explicit/derived/assumed/unknown) from confirmation and lock.
Record source message or KB record/version, rule, timestamp and uncertainty where applicable.
A lock is independent of provenance. Unknown cannot silently become assumed; inferred values require traceable policy.
Concurrent state writes require revision checks. Jobs require idempotency and bounded retries before deployment.
All foreign-key ownership checks must prevent cross-tenant access.

Binary assets belong in private GCS; PostgreSQL contains metadata and object identifiers, not image
bytes or signed URLs. Temporary read URLs are ephemeral bearer capabilities and are never durable
model state.
Local repository data/ contains non-sensitive versioned catalogs only.
