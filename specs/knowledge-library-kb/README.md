# Knowledge Library Contract 2.0.0 (`kb`)

Owner-approved [Architecture v1.2](https://docs.google.com/document/d/17cYWdLIqPfrxWuCfvXNyMODpe-fv6_Flrk5VOJJMrWw/edit)
and [ADR 0048](../../docs/adr/0048-knowledge-library-kb-postgresql-contract-2.md).
[`contract-2.0.0.json`](contract-2.0.0.json) is generated from
`jewelai_domain.kb_contract.contract_document()`; a domain test fails if they differ.

## Storage

PostgreSQL is the only writable source. The logical schema `kb` is implemented as `kb_*`
tables in the application schema (migration `0024_knowledge_kb_foundation`), so the existing
Alembic check and per-schema disposable-PostgreSQL isolation apply unchanged.

- Revisions (`kb_claim_revision`, `kb_evidence_revision`, `kb_policy_revision`,
  `kb_validation_profile_revision`, `kb_term_revision`, `kb_term_relation_revision`,
  `kb_rule_revision`) start as `draft`; once `published` they cannot be updated or deleted.
- Release membership is explicit: `kb_release_claim` (one revision per claim per release) and
  `kb_release_artifact` (one revision per object per kind). Releases, membership, legacy map,
  change log, retirement records and the active-pointer log are append-only; TRUNCATE is refused.
- `kb_active_release` is the only switchable row; every switch is logged by a trigger.
- Roles `kb_reader` (SELECT) and `kb_admin` (draft writes) are created if missing.

## Lifecycle (`jewelai_persistence.knowledge_kb.KbAdmin`)

`draft_*` → `candidate` → `validate` (structure, content profiles, consistency, permissions) →
`diff` → `publish(release_id)` → `activate`. Publishing the same `release_id` again with no new
drafts returns the existing release; pending drafts under an existing ID are `payload_conflict`.
`revert` writes a new release with an earlier membership. `export_release`/`import_release`
move a release between independent deployments with an identical checksum.

## Knowledge API (`KnowledgeApi`)

Every call names a caller and a purpose and runs in a READ ONLY transaction. Facts require a
pinned `release_id`; only `get_release("active")` resolves the pointer. The release's own policy
revision decides the allowed uses. `verify_evidence`, `resolve`, `search` and
`release_metadata` never grant an action. `validate_block` is disabled.

| Operation | Purpose | Returns |
|---|---|---|
| `get_release` | `release_metadata` | manifest, checksum, policy and profile revisions |
| `resolve_terms` | `resolve` | candidates, ambiguity, false-equivalence warnings |
| `get_claims` | action uses | permitted claims with provenance, typed denials |
| `evaluate_claim` | `verify_evidence` | supported / contradicted / unknown / review_required |
| `evaluate_rules` | `validate_warn` | rule metadata; nothing is enforced in the pilot |
| `search_knowledge` | `search`, `explain` | matches with caveats; never prompt permission |

## Validation profiles

Only profile outcome `source_match` may be published as VERIFIED. There is no universal
numeric tolerance: Mohs is ordinal, RI is a source range, Stuller sizes are approximate points
(derived points are estimates), ring conversions apply the EV-RING formulas with a declared
rounding, and attributes without a comparable source (`manual_source_review`) never match.
