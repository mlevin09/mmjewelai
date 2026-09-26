# Planned data model and storage boundary

This remains the broader logical model. The runtime physically implements organization, project,
auth_principal, organization_membership, design_session, message, specification_revision,
question_event, prompt_revision, generation_run, generation_dispatch_outbox, and asset; see ADRs
0007–0017 and the Alembic
migrations. Later rows remain plans, not implemented
claims.

| Entity | Scope / relationships |
| --- | --- |
| auth_principal | External `(issuer, subject)` identity plus optional verified metadata; tokens are never stored |
| organization, organization_membership | Tenant and owner/admin/member access; separate from conversational role |
| project | Belongs to one organization |
| design_session | Project, selected role, locale, conversation state and pinned artifact versions |
| message | Implemented user-message lineage: session, bounded content, server timestamp; privacy/retention policy pending |
| specification_revision | Immutable session revision, parent revision, schema version and field state |
| question_event | Semantic question ID/version, rule/version, target, answer and decision explanation |
| prompt_revision | Implemented immutable specification link, template/compiler versions, validated structured prompt, text and hash |
| generation_run | Implemented immutable prompt/profile/provider/config input, pending/running/succeeded/failed lifecycle, active linear attempt/immediate-parent retry lineage and metadata-only result/error; provider bytes remain transient |
| generation_dispatch_outbox | One row per API-created GenerationRun; pending until deterministic Cloud Task publication succeeds. Stores no task body or secret and is not a GenerationRun lifecycle state. |
| asset | Implemented private metadata: organization/project/session, object key, type/hash/size, optional parent and generation-output lineage, pending/ready/failed lifecycle |
| experiment_assignment / event | Stable assignment, variant, outcome and related run/spec revision |

Field state separates value origin (explicit/derived/assumed/unknown) from confirmation and lock.
Record source message or KB record/version, rule, timestamp and uncertainty where applicable.
A lock is independent of provenance. Unknown cannot silently become assumed; inferred values require traceable policy.
Concurrent state writes require revision checks. Jobs require idempotency and bounded retries before deployment.
All foreign-key ownership checks must prevent cross-tenant access.

Binary assets belong in private GCS; PostgreSQL contains metadata and object identifiers, not image
bytes or signed URLs. Temporary read URLs are ephemeral bearer capabilities and are never durable
model state. Authenticated organization members may mint them only for scoped READY Assets; current
membership is checked for each issuance, while an already-issued URL remains usable until expiration.
OpenAI base64 is decoded only in memory; every generated output is durably written to
its deterministic final private object key before GenerationRun success. Asset metadata is finalized
afterward without a second storage write. Reconciliation of durable objects with missing metadata is
implemented through exact metadata-only inspection; failed-run orphan deletion is delayed and
version-conditional.
Local repository data/ contains non-sensitive versioned catalogs only.

Generation attempt 1 requires a NULL parent. Attempts greater than 1 require the immediate failed
parent, and a unique parent reference permits only one direct retry child. Each child has its own
atomic dispatch-outbox row. Timeout recovery records `FAILED(execution_stale)` on an old RUNNING row
without altering its outbox or creating a retry.

Persistence also records nullable internal `generation_run.assets_reconciled_at` and
`generation_run.orphan_cleanup_completed_at` timestamps. They provide bounded maintenance progress
only and are deliberately absent from the public Model Gateway `GenerationRun` contract. Successful
runs are marked reconciled only after every expected generated Asset is exact and READY; failed runs
are marked cleanup-complete only after every expected ordinal is absent or conditionally deleted.
