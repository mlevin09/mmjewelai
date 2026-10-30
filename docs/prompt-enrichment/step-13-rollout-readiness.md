# Prompt Enrichment Step 13 rollout-readiness assessment

Status: `INTERNAL_VALIDATION_PASSED`
Assessment scope: internal integration validation only
Baseline: `jewelai-v2` at `63f326988f089a181d1550c554776cbe241d16e6`

This label is an assessment, not a feature flag or production approval. The controlled HTTP surface
remains absent from default application composition.

## Constraint-preservation correction

PR 13C preserved non-schema constraints only as an unasked candidate ID/reason. That representation
lost the authoritative kind, semantic subject, source span, active/superseded state, and normalized
meaning before `FinalPromptSnapshot`, so an explicit `no halo` could disappear after restart.

This change selects the typed-evidence fallback allowed by the boundary contract. Canonical Product
State binding was rejected for this narrow case because the existing `visual_constraints` aggregate
has one aggregate State provenance and cannot represent independent source spans, applicability, or
supersession for multiple constraints without loss. `FullMessageParseResult` v1.1 identifies only a
small allowlist of supported semantic subjects. `ClarificationPlan` v1.1 stores the resulting typed,
hashed evidence in its existing append-only durable payload. `InternalFinalPrompt` v1.1 includes the
complete evidence history but emits only active evidence as authority. The user-readable description
renders only normalized, applicable instructions and never exposes IDs or hashes.

Tests cover English, Russian and mixed-language halo prohibitions, engraving prohibition, band
preservation, superseding and reaffirming corrections, unbound ambiguity, an unaccepted/rejected
recommendation, restart and idempotent clarification, correction/re-enrichment, cross-scope
rejection, nested-payload tampering, legacy v1.0 plan rejection, rollback, and PostgreSQL correction
concurrency. The full HTTP test inspects the structured final artifact, active/superseded evidence,
description, exact Product State revision, and exact pinned Knowledge release.

## Verified capabilities

- A persisted user message enters the deterministic full-message parser before enrichment; the
  controlled path makes no external text-understanding or generation call.
- One verified synthetic ACTIVE Knowledge Library release is pinned to the session and remains
  identical through initial enrichment, restart, clarification, correction, and final assembly.
- Initial Product State revision, release pin, enrichment cycle, and complete clarification plan
  commit atomically.
- A fresh application and runtime-service instance restore the exact authoritative state and plan
  from persistence without process-local memory.
- A persisted answer is checked against its durable plan and offered options. An identical retry
  after restart returns the existing result; conflicting or stale input fails closed.
- A persisted correction creates append-only revision, cycle, plan, and correction lineage while
  preserving unchanged canonical Product State.
- Explicit non-schema requirements, prohibitions, and preservation instructions are represented by
  a minimal typed evidence contract because Product State v1 `visual_constraints` cannot preserve
  per-constraint source spans, revision/cycle lineage, applicability, and supersession without
  semantic loss. Product State remains authoritative for every representable design fact.
- Constraint evidence is derived only from verified deterministic parser candidates and exact
  persisted-message provenance. It is hashed, organization/session scoped, bound to its source
  revision and enrichment cycle, and stored inside the existing append-only clarification-plan JSON
  payload. No migration was required.
- Later explicit evidence for the same semantic subject supersedes prior active evidence. Historical
  evidence remains auditable, while only one current active constraint can reach final assembly.
  A compatible canonical reaffirmation fulfils an existing explicit preservation instruction;
  it is not authority to revoke KEEP. Its new source is retained as covered/superseded evidence
  pointing to the active KEEP. Compatibility uses the actual preserved fact in the immutable
  source revision and current canonical state, not wording, locale, or Matrix outcome alone.
  New approved preservation still uses normal same-kind supersession. This grants no cancellation
  action or intrinsic LOCK; unsupported conflicting/cancellation requests remain non-authoritative.
  The description displays active explicit preservation evidence, including canonical targets,
  once; superseded/rejected evidence does not become a displayed instruction.
  Ambiguous evidence remains unresolved and recommendations remain non-authoritative until accepted.
- The user-readable description and provider-neutral `InternalFinalPrompt` are assembled from the
  same authoritative revision and carry deterministic hashes and exact Knowledge release lineage.
- Organization membership and session scope protect every controlled endpoint.
- Default application composition omits the controlled routes and retains the legacy workflow.

## Test evidence

The focused HTTP integration test uses the real FastAPI routes, authentication/organization
dependencies, persistence repository, deterministic parser, Matrix/Policy enrichment, synthetic
verified ACTIVE release, clarification/correction services, and final-output assembler. Only
external boundaries use deterministic fakes.

Validated commands for this change:

```text
python3 -m pytest -c apps/api/pyproject.toml \
  apps/api/tests/test_prompt_enrichment_integration.py \
  apps/api/tests/test_prompt_enrichment_http.py \
  apps/api/tests/test_prompt_enrichment_runtime.py -q

python3 -m pytest -c apps/api/pyproject.toml apps/api/tests -q
python3 -m pytest -c packages/domain/pyproject.toml packages/domain/tests -q
python3 -m pytest -c packages/parser/pyproject.toml packages/parser/tests -q
python3 -m pytest -c packages/prompts/pyproject.toml packages/prompts/tests -q
python3 -m ruff check apps/api packages/domain packages/parser packages/prompts packages/persistence
python3 -m ruff format --check \
  apps/api packages/domain packages/parser packages/prompts packages/persistence
git diff --check
```

Local results on the PR branch:

- Runtime API: `266 passed, 19 skipped` (the skips require PostgreSQL or optional integrations);
- Domain: `315 passed`;
- Parser: `46 passed`;
- Prompts: `65 passed`;
- Knowledge behavioral and three-stone regression: `7 passed`;
- Ruff lint and format: passed;
- SQLite Alembic upgrade/check/current: passed at `0014_clarification_plans (head)`;
- `git diff --check`: passed.

PostgreSQL-gated Runtime API CI executes concurrent initial, answer, and conflicting-correction
transactions. The correction race verifies one commit and no partial cycle/plan/constraint history.
Locally skipped PostgreSQL cases are not counted as passing evidence. GitHub workflow links and exact
final counts are recorded in the pull request completion report after checks finish.

## Database state

Alembic head is `0014_clarification_plans`. Migration 0014 creates immutable clarification-plan
storage and the optional answer-to-plan lineage foreign key. Upgrade, autogeneration drift check,
and current-head checks run in Runtime API CI against PostgreSQL.

Migration 0014 has not been applied to production by this work. No production migration, catalog
activation, or deployment is authorized by this assessment.

## Knowledge Library prerequisites

Tests use the existing synthetic, fully validated three-stone artifact and explicit ACTIVE envelope.
Production activation still requires a separately reviewed real catalog with:

- complete all-PASS production-validation evidence;
- exact package ID and artifact version;
- matching runtime SHA-256 and validation-report SHA-256;
- durable, immutable release artifacts available to the runtime;
- approved runtime configuration selecting that exact release.

There is no latest-release lookup and no Google Drive runtime fallback.

## Compatibility and rollout isolation

`PromptEnrichmentRuntimeService` must be explicitly injected into `create_app()` for the five
versioned routes to exist. Without injection:

- the routes are absent from OpenAPI and return 404;
- legacy session, message, Parser Proposal, revision, prompt, generation, and Asset behavior is
  unchanged;
- the legacy Google text-understanding adapter is neither replaced nor called by this module;
- no catalog is loaded and no background/provider work is scheduled by Prompt Enrichment.

Existing clients therefore remain on the legacy path until a separately reviewed composition and
rollout decision.

## Restart, retry, concurrency, and rollback

Restart tests rebuild both FastAPI and `PromptEnrichmentRuntimeService` against the same database and
artifact store. State, plan order/options/hash, release lineage, and final-output snapshot restore
from durable records. Exact retries are idempotent; conflicting retries and stale plans return typed
conflicts.

PostgreSQL tests race two initial requests and two conflicting answers. Each permits at most one
authoritative commit and verifies no duplicate or partial revision/cycle/plan history. Injected plan
write failure rolls back revision, release pin, cycle, and plan together.

Rollback before activation is composition-only: omit the explicit service injection and the legacy
path remains available. Durable module history is append-only and does not corrupt legacy Product
State. Once production writes exist, database rollback must preserve migration 0014 data; disabling
routes must not delete or heuristically reconstruct history.

## Remaining risks and gaps

- No real production Knowledge Library catalog has been validated or activated.
- The module has not been composed into a deployed runtime or verified in preproduction.
- Existing pre-0014 enrichment cycles have no durable plan. They fail closed and are not
  heuristically reconstructed or automatically migrated.
- Current deterministic RU parsing preserves source text and language evidence, but some inflected
  RU domain terms are not yet normalized into canonical Product State. This is a known language
  coverage gap, not permission for inference or an external-provider fallback.
- Deterministic parser coverage is deliberately narrow: the validated EN/RU/mixed halo forms,
  engraving prohibition, side-stone prohibition, and supported preservation phrases are recognized.
  General Russian morphology and arbitrary natural-language constraints remain unsupported and must
  remain unresolved rather than inferred.
- Clarification plan v1.0 histories predate typed constraint evidence. They fail closed as
  incompatible; the runtime does not guess or claim restoration of evidence it never stored.
- The controlled HTTP response now exposes exact non-secret release lineage for auditability, but
  clients still have no release-selection authority.
- `InternalFinalPrompt` remains distinct from legacy `CompiledPrompt`; no provider adapter consumes
  it yet. Provider-specific formatting and generation handoff require a separate reviewed task.
- Operational monitoring, runbook procedures, catalog provisioning, security review, migration
  rehearsal, and rollback rehearsal remain unverified.

## Activation prerequisites

1. Approve and publish a real all-PASS ACTIVE catalog to durable runtime storage.
2. Rehearse migration 0014 and backup/rollback procedures in preproduction.
3. Add explicit disabled-by-default runtime composition/configuration in a separate reviewed change.
4. Verify authorization, integrity failures, structured observability, and restart/concurrency under
   deployed PostgreSQL.
5. Validate RU/EN catalog language coverage accepted for the rollout cohort.
6. Define the typed downstream adapter boundary from `InternalFinalPrompt` without replacing legacy
   `CompiledPrompt` prematurely.
7. Complete preproduction acceptance and obtain release approval before any production traffic
   switch.

## Classification rationale

`INTERNAL_VALIDATION_PASSED` means the Step #13 controlled flow now demonstrates restart-safe
constraint preservation through real HTTP orchestration, clarification, correction, final snapshot,
description, and provider-neutral final assembly. It includes deterministic EN/RU/mixed prohibition,
preservation, supersession, recommendation-authority, integrity, legacy-compatibility, rollback and
PostgreSQL concurrency coverage. It is not production approval: the real catalog, deployed runtime
composition, operational controls, migration rehearsal, and downstream provider handoff remain
separate Step #14 prerequisites.
