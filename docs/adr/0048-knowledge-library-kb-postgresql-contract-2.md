# ADR 0048 — Knowledge Library Contract 2.0: PostgreSQL `kb` schema as operational source

Status: Owner-approved 2026-11-21; implementation pending in Draft PRs and independent review.
Not a shared migration execution, release, activation or deployment. EN MASTER, 2026-11-21. Russian copy: [0048 RU](0048-knowledge-library-kb-postgresql-contract-2.ru.md).

## Context and authority

On 20 November 2026 the Owner approved
[Knowledge Library Architecture v1.2](https://docs.google.com/document/d/17cYWdLIqPfrxWuCfvXNyMODpe-fv6_Flrk5VOJJMrWw/edit).
It names one PostgreSQL schema `kb` as the source of truth for knowledge revisions and
releases, immutable published revisions with explicit release membership
(`release_claims`, `release_artifacts`), purpose-specific permissions taken from
Knowledge Library v1.6.2, release pinning per session, and a read-only Knowledge API
module inside the existing backend. v1.2 itself does not authorize migrations,
ACTIVE publication or deployment.

On 21 November the Owner additionally:

- authorized the Knowledge `kb` work block (phases 0, A, B1, B2, B3 of v1.2 §11) and
  migrations in development/CI only;
- assigned implementation to Claude in Draft PRs from `jewelai-v2`, without self-merge
  or deployment;
- required re-qualification of imported VERIFIED records against validation profiles
  before the first publication (v1.2 ARCH-KB-03);
- clarified that a possible Russian cloud deployment is an independent parallel project
  with its own code and database, not a replica of the Google Cloud database.

v1.2 does not account for knowledge components that already exist in `jewelai-v2`:

- Knowledge Library Contracts 1.0.0/1.1.0 (ADR 0027, 0028), with source/runtime/manifest/
  checksum artifacts in a filesystem store (ADR 0029) and data in `data/knowledge/`;
- the immutable per-session `knowledge_release_binding` and exact contract-version
  dispatch (ADR 0035, migration 0017);
- Domain Dictionary v1.0.0 (Parser normalization and Product State domain IDs);
- Rules Engine v1/v2 (sole authority for ask/derive/assume/block decisions);
- the parametric gemstone knowledge base (`data/knowledge-base/v1.0.0.json`).

`AGENTS.md` also defers new professional Knowledge catalogs and releases to the Owner.
This ADR records how Contract 2.0 coexists with those components so that the project
does not acquire two competing knowledge systems.

## Decision

1. **New contract, not a rewrite.** Knowledge Library Contract 2.0.0 is the v1.2 model
   stored in PostgreSQL schema `kb`. PostgreSQL is the operational source for 2.0 content,
   following the precedent of ADR 0044 (Roles). No 1.x artifact is converted, re-hashed or
   reinterpreted as 2.0. Implementation note: the logical schema `kb` is realised as `kb_*`
   tables in the application schema, so the existing Alembic check and the per-schema
   disposable-PostgreSQL test isolation apply unchanged.

2. **The 1.x JSON library becomes an archive.** The Owner's target state (21 November) is
   that today's JSON library is kept as a backup for history, not as a working tool.
   - An archival snapshot was taken on 21 November 2026 from `jewelai-v2` commit
     `663070223383da27325b70be279d323fd185f831`: `data/knowledge/`, `data/knowledge-base/`,
     `specs/knowledge-library/` and `specs/knowledge-base/` (14 files with per-file SHA-256 in
     `MANIFEST.json`). Archive SHA-256:
     `ee92dcbcc40f3126dc6e8ec7cbaad55f5e474b211971a460e7a832221d7e136f`. It is stored in the
     project Drive folder «Library and Matrix/Архив». Full change history stays in git.
   - Until Contract 2.0 is integrated (v1.2 phase C), the current Prompt Enrichment still
     depends on the 1.x runtime, so it is not removed in this block.
   - After phase C, new sessions use only 2.0. The 1.x data and loaders are kept read-only
     so that historical sessions stay viewable (Owner decision, 21 November).

3. **Dispatch by exact contract version.** Consumers select 2.0 only through the ADR 0035
   mechanism (`PROMPT_ENRICHMENT_KNOWLEDGE_CONTRACT_VERSION=2.0.0`). This block does not add
   or enable that value; consumer integration (v1.2 phase C) needs separate approval and
   depends on Conversational Core D5.

4. **Session pinning reuses the existing binding concept.** A 2.0 binding will carry the
   `kb` release ID, manifest checksum and policy revision ID. The binding DTO and migration
   change belong to phase C. In this block `get_release` exposes everything needed for a
   later binding, and release checksums are verifiable.

5. **Dictionary keeps its authority.** Dictionary remains the normalization and domain-ID
   authority for Parser and Product State. `kb.terms`/`kb.term_relations` are the
   professional terminology layer behind `resolve_terms` (RU/EN names, synonyms,
   ambiguity, false equivalences). `kb.entities` has an optional `dictionary_domain_id`.
   Nothing is synchronized automatically; `kb_validate` reports mismatches as warnings.

6. **Rules Engine keeps its authority.** `kb.rules` are qualified knowledge constraints
   returned as metadata by `evaluate_rules`. They do not ask, derive, assume or block on
   their own. Feeding them into the Rules Engine (for example as `AvailableKnowledgeFact`)
   is later, separately approved work. In this block there are no executable `kb` rules,
   `validate_block` is disabled and `evaluate_rules` is preview-only on test fixtures.

7. **Parametric knowledge base unchanged in this block.** `data/knowledge-base/v1.0.0.json`
   is not modified or migrated; it is included in the archive snapshot of decision 2.
   Overlap with `kb` (for example gemstone dimensions) is reconciled in a later phase,
   not silently.

8. **Each deployment has its own `kb`.** There is no cross-cloud replication; this
   supersedes the replica part of v1.2 §10. A published release can be exported as a
   portable package (revisions, evidence, terms, rules, policies, validation profiles,
   manifest, checksum) and imported into another deployment with an identical checksum.
   The package is derived and read-only; it is never edited as a second authority.

9. **Re-qualification before publication.** v1.6.2 records are imported as drafts with their
   legacy K-IDs. A record is published as VERIFIED only after its validation profile
   passes (exact source, atomic claim and scope); otherwise it is published as REFERENCE
   ONLY with a recorded reason. No universal tolerance (RI ±0.01, SG ±0.03, Mohs ±0.25) or
   strict Stuller monotonicity is used.

10. **Caller authorization.** A `kb` table maps backend caller IDs (for example the
    Semantic Orchestrator, consultant, trainer and admin tooling) to allowed purposes. These
    are backend components, not the professional Roles of ADR 0044 and not user permissions.

11. **Database protection.** Triggers reject UPDATE/DELETE of published revisions and
    release membership. Two database roles are used: an admin role that may write drafts
    and call the publication functions, and a reader role that can only read published
    data. Ordinary admin edits go through the `kb_*` functions.

## Scope of this block (v1.2 phases A–B3)

| Phase | Output |
|---|---|
| A. Contract | `specs/knowledge-library-kb/` with contract 2.0.0, schema, scope vocabulary, validation profiles for the pilot attributes, policy revision 1 (from v1.6.2), API DTOs and typed errors |
| B1. Storage | Alembic migration for `kb`, immutability triggers, roles; `kb_validate`, `kb_diff`, `kb_publish`, `kb_revert`; tests on a disposable PostgreSQL |
| B2. Pilot slice | Import from v1.6.2: corundum (ruby, sapphire), approximate diamond sizes, ring-size conversions, purity conversions, and a few GOST alloys plus generic Ag 925/Pt 950 for negative tests; re-qualification; `legacy_map`; release `kb-2.0.0-pilot` in development only |
| B3. Knowledge API | Read-only module in `apps/api`; six operations; acceptance criteria AC-01…AC-11 for the slice and the eleven mandatory negative tests of v1.2 §12 |

| D. Full corpus (Owner-authorized 21 November) | All 17 682 v1.6.2 K-IDs as release `kb-2.1.0`: VERIFIED records re-qualified against the recorded source fragments; all other records kept as REFERENCE ONLY / REJECTED text claims grouped by normalized subject; every K-ID in `legacy_map` |

Excluded: SO and IFP integration (AC-12), enabling contract 2.0 in runtime configuration,
shared or preprod migration execution, ACTIVE activation, deployment, and any change to
Dictionary, Rules, the parametric knowledge base or 1.x Knowledge artifacts.

Terms (Owner, 21 November): v1.6.2 term rows move into `kb_term_revision` with
`review_status` (`curated`, `source_match`, `unreviewed`). Imported terms are `unreviewed`:
`resolve_terms` returns them flagged, ranks reviewed terms first and computes ambiguity over
reviewed candidates, so an unreviewed term is a hint and never a normalization. ГОСТ Р
52793-2007 covers only 97 precious-metal production terms without English equivalents, so a
domain terminology review remains necessary before terms are promoted.

## Owner decisions on open questions

1. Historical 1.x sessions must stay viewable after phase C (Owner, 21 November). The 1.x
   data and loaders are kept read-only for historical sessions only; new sessions never
   use them.

## Alternatives

- **Replace 1.x runtime with `kb` and migrate old sessions.** Rejected: rewrites historical
  identities that ADR 0035 forbids reinterpreting.
- **Compile `kb` into 1.1 filesystem artifacts.** Rejected: the 1.1 model targets Product
  State policies and has no purpose-specific permissions or release membership; it would
  also make files a second authoritative path, contrary to v1.2 principle 1.
- **Store `kb` terminology in the Dictionary.** Rejected: the Dictionary is a bounded,
  reviewed normalization seed for Parser with its own lifecycle.
- **Separate microservice.** Rejected by v1.2: the API is a module of the existing backend.
- **Database replication between clouds.** Rejected by the Owner on 21 November: the
  deployments are independent projects.

## Consequences

- Two knowledge contract lines coexist until phase C; afterwards 1.x is archive-only.
- Terminology may be defined both in the Dictionary and in `kb`; mismatches are visible
  through validation warnings until a reconciliation decision is made.
- Role creation and trigger installation on Cloud SQL need suitable migration privileges;
  this is verified before any shared migration request.
- Pilot publication proves the storage and API contracts, not the professional
  completeness of the library.

## Validation

Phase B tests run on a disposable PostgreSQL that passes the existing safety gate. They
must cover at least: idempotent publication and typed conflict for a different payload;
rejection of UPDATE/DELETE on published rows and membership; release N data unchanged
after N+1 is published; purpose filtering by the release's policy revision; typed
errors for unknown or unavailable releases; profile-based re-qualification (Mohs as an
ordinal or interval value, equal Stuller diameters allowed for different weights);
generic Ag 925/Pt 950 never VERIFIED; GOST alloy densities and care guidance never
returned for `purpose=prompt`; ambiguity and false equivalences in `resolve_terms`;
`review_required` on conflicting evidence; preview-only rules; no Product State
writes; and a complete `legacy_map` entry for every imported K-ID.
