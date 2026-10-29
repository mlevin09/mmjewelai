# ADR 0035 — Explicit Knowledge v1.1 session integration

Status: Owner-approved D1/D2/D3; implementation pending independent review.
Date: 2026-10-29. Refs #119, Owner approval comment 6495079862.

## Context

Knowledge v1.1 compilation, immutable storage, ACTIVE/report validation, qualification and canonical
Policy Engine support already exist. Controlled sessions still used v1.0-only consumers. Standalone
qualification does not prove an application session works. Knowledge remains a reusable domain
component independent of applications, persistence, storage providers and image generation.

## Decision

Use exact contract/schema dispatch, separately from artifact version, Product State version and
qualification-contract version. Enabled startup requires
`PROMPT_ENRICHMENT_KNOWLEDGE_CONTRACT_VERSION=1.0.0|1.1.0` in addition to the existing exact release
configuration. A configured v1.0 runtime is for verified historical restoration only: **new controlled
initial enrichment requires 1.1.0**. Missing/invalid v1.1 evidence fails closed. No latest lookup,
validator-probing, automatic activation, package-name inference or downgrade exists.

Reuse both existing stores, compilers, envelopes, reports and qualifiers. Parser/matcher/enrichment
read the actual selected compiled type. Existing Dictionary/Knowledge source distinctions, deferred
unsupported targets, explicit acceptance, canonical LOCK checks and revision/CAS remain authoritative.
This integration does not add semantic mappings or automatically promote recognized concepts to facts.

`KnowledgeReleaseBinding` version 1.0.0 is a new immutable release-identity DTO. It binds explicit
Knowledge contract/schema, package/artifact, runtime/report SHA-256, canonical verified ACTIVE-envelope
SHA-256, independently reloaded source/manifest SHA-256 and its canonical content hash. Canonical
hashing is sorted compact JSON, ensure_ascii=false, allow_nan=false, SHA-256 over exact UTF-8.
The two independent store reads must agree on runtime identity.

Migration 0017 adds one append-only binding per session, scoped to its actual first cycle/revision
via a composite FK, plus a nullable Knowledge contract marker on the initial cycle. Binding, marker,
four-field session pin, optional revision, first cycle and clarification plan commit in the existing
single transaction. PostgreSQL rejects binding UPDATE/DELETE. Read paths validate the payload hash,
relational hash, release tuple, marker and organization scope, then reverify the actual release.
Correction validation reuses its existing transactional Session for binding reads; it must not open
a nested Session that could roll back a shared in-memory connection's outer transaction.
Preparation row validation likewise passes its existing transaction to release-pin verification.

Historical cycle/answer/correction/IFP bytes and schemas are not rewritten. Existing four-field
references associate indirectly through the immutable binding. A historical NULL marker/no binding
uses the explicit legacy v1.0 path only, with the v1.0 store and ACTIVE/report verification. A marked
cycle without its binding fails closed; a legacy pin cannot restore through a v1.1 store. Startup
with another release never migrates an existing session. Historical releases needed for restoration
must remain explicitly available; missing evidence is an error, not a fallback.

Current structured enrichment 1.3 and IFP/handoff 2.1 remain unchanged; capacity is still 32,000
characters/128,000 UTF-8 bytes, with independent description/execution bounds. Existing earlier valid
commits retained by the PR #132 operation-boundary contract are not retroactively rolled back when
later read-only final assembly overflows. No successful partial handoff is returned.

## Alternatives and consequences

- Coerce v1.1 into v1.0 or select by artifact version: rejected; loses explicit contract authority.
- Rewrite every nested historical DTO: rejected under approved D3; immutable binding provides the
  explicit identity without rewriting old hashes.
- Rebuild professional content or expand extraction targets: excluded; unsupported evidence remains
  deferred and requires separately approved semantics.

This changes enabled-runtime configuration, not deployment variables. No real catalog is selected,
published or activated. Synthetic all-PASS reports are fixture evidence only. A real catalog still
requires reviewed production qualification and an explicit release/deployment decision.

Rollback disables new v1.1 intake but retains bindings and all historical artifacts. Online downgrade
refuses before DDL; dropping retained bindings requires a separately reviewed retention plan. An old
runtime must not reinterpret a v1.1 session as v1.0.

## KRT executable acceptance map

| KRT | Tests |
| --- | --- |
| 001 | test_new_session_rejects_legacy_but_historical_pin_restores_without_rewriting; existing enrichment history/goldens |
| 002 | test_exact_version_rejection_before_defaulting; test_explicit_store_version_never_falls_back; new-session legacy rejection |
| 003 | P0-21 standalone tests; test_exact_identity_binding_and_unchanged_models |
| 004 | composition missing/corrupt/tampered-evidence tests; failed-initial report case |
| 005 | test_enabled_composition_qualifies_release_and_runs_restart_safe_full_http_cycle (EN/RU/mixed, observed real parser) |
| 006 | test_v1_1_only_policy_survives_full_http_lifecycle: composition.symmetry_mode policy in all three cycles; existing LOCK/stable-ID suites |
| 007 | full HTTP cycle; binding counts/identity assertions |
| 008 | full HTTP cycle clarification question/SELECT_OPTION |
| 009 | full HTTP cycle correction; four-turn collision regression |
| 010 | full HTTP restart; historical pin restoration and versioned history tests |
| 011 | full HTTP final output; real READY capacity sessions; frozen handoff reader tests |
| 012 | explicit-version and binding tamper tests; wrong-report rollback case |
| 013 | test_verified_binding_requires_actual_immutable_artifacts; existing store collision tests |
| 014 | atomic/concurrent binding tests; test_staticpool_preparation_post_get_replay_are_durable and PostgreSQL roundtrip variant; tenant/CAS tests |
| 015 | existing canonical LOCK/provenance tests and real READY projection equality |
| 016 | existing parser/policy invalid target/group and unsupported evidence tests |
| 017 | existing 32,000/32,001 and UTF-8 capacity tests; unchanged renderer limits |
| 018 | duplicate/concurrent binding, full HTTP restart, StaticPool preparation GET/replay, retained preparation replay and old hashes |

Only actual passing runs count as evidence. PostgreSQL tests use the existing independently verified
CI container/schema gate; absence of verified disposable PostgreSQL is a SKIP, not a local PASS.

## Owner-approved C2 T10-10 raw-text slice

Issue #125 [Owner decision 6502450359](https://github.com/mlevin09/mmjewelai/issues/125#issuecomment-6502450359)
authorizes only the first P0-10 symmetry slice. The source-backed fragment and
per-record register live in `data/knowledge/v1_1/p010-symmetry-0.1.0.json` and
`p010-symmetry-provenance-0.1.0.json`. Original source SHA-256 is
`43cda0eddf6e33dc15a120ad8c0025ed047824f4a98d377726edee70587b6b64`.
Scoped REVIEWED internal decisions do not imply external factual approval or
approval of all original P0-10 proposals. Private source archives remain outside Git.

`parse_full_message` reuses the v1.1 matcher for exact contextual RU/EN language
surfaces, then emits existing untrusted structured evidence. The consumer re-derives
that evidence from original text and the verified pinned runtime. It binds only
the approved explicit `composition.symmetry_mode=asymmetrical` to an existing
`EnrichmentProposal`. No legacy ParserTarget, public DTO or durable schema changes.
No symmetry is inferred from Art Deco/organic/geometric cues. Ambiguous/rejected
language remains deferred or prohibited; unsupported evidence retains original text.

For a missing/Unknown/NotApplicable composition aggregate, existing canonical
projection has no addressable child. The existing complete-aggregate proposal
carries exactly the explicit symmetry child, with other fields absent. Canonical
Policy v2 evaluates the real parent and its precedence, LOCK and applicability.
Existing known aggregates use a leaf proposal. There is no preseed revision,
parallel policy engine or factual inference. STYLE-10-02/06/07 remain descriptive
policy records, observable on the actual symmetry Matrix cell after EDIT.
Only APPLIED decisions join the existing parser's proposed design before normal
revision validation and transactional CAS. Confirmed/LOCKED/N/A values are protected.

The literal preservation instruction uses existing constraint evidence and IFP 2.1
preservation constraints. It creates no confirmation/LOCK and becomes an active
instruction only when the canonical symmetry is actually asymmetrical. Corrections
and clarification retain original message provenance and immutable release binding.
Schema 1.0 sessions are not silently upgraded; the HTTP test uses the existing explicit
schema 1.1 upgrade endpoint on an empty session before submitting the original text.

The HTTP lifecycle fixture has a clearly synthetic test identity/report/ACTIVE;
its P0-10 fragment is authentic. It is not professional qualification evidence.
The real recovered-core extension is DRAFT 0.2.0, with no ACTIVE envelope/report;
the prior 0.1.0 qualification cannot be reused for its different runtime hash.
Full production qualification and promotion remain separate gates. No live release
selection, migration, provider, worker, UI or deployment is changed here.

Full T10-12 three-signal preservation, structured hierarchy/rhythm, multi-value
organization, inscription text/color, creative metadata, geometric ambiguity,
unrelated concept/source collisions and prior professional deferrals remain out
of scope. The bounded T10-12 regression makes no full-acceptance claim.
