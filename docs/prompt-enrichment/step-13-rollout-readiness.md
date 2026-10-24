# Prompt Enrichment Step 13 rollout-readiness assessment

Status: `BLOCKED`  
Assessment scope: internal integration validation only  
Baseline: `jewelai-v2` at `936581c9deb194054941e7cd08c80ed175f88bb6`

This label is an assessment, not a feature flag or production approval. The controlled HTTP surface
remains absent from default application composition.

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
  preserving unchanged canonical Product State. Constraint evidence remains durable in the
  clarification/correction history, but the final-output snapshot gap described below is blocking.
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

- focused integration/runtime/HTTP: `23 passed, 3 skipped` (the skips require PostgreSQL);
- Runtime API: `262 passed, 18 skipped` (the skips require PostgreSQL);
- Domain: `315 passed`;
- Parser: `40 passed`;
- Prompts: `58 passed`;
- Knowledge behavioral and three-stone regression: `7 passed`;
- Ruff lint and format: passed;
- SQLite Alembic upgrade/check/current: passed at `0014_clarification_plans (head)`;
- `git diff --check`: passed.

PostgreSQL-gated Runtime API CI is required to execute concurrent initial and answer transactions;
locally skipped PostgreSQL cases are not counted as passing evidence. GitHub workflow links and
exact final counts are recorded in the pull request completion report after checks finish.

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
- Explicit prohibitions and preservation instructions that do not map to an existing parser target
  are classified and retained as clarification evidence, but the current durable plan records only
  their candidate ID/reason and `FinalPromptSnapshot` does not consume that evidence. Therefore an
  instruction such as `no halo` is not safely reproducible in `InternalFinalPrompt` after restart.
  Resolving this requires an approved structured binding to canonical `visual_constraints` or a
  versioned final-snapshot constraint-evidence contract; PR 13C deliberately does not invent one.
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
6. Approve and implement a structured durable prohibition/preservation handoff into the final
   snapshot, with provenance and restart-safe tests.
7. Define the typed downstream adapter boundary from `InternalFinalPrompt` without replacing legacy
   `CompiledPrompt` prematurely.
8. Complete preproduction acceptance and obtain release approval before any production traffic
   switch.

## Classification rationale

`BLOCKED` means the orchestration and controlled HTTP boundary are internally integrated, but the
first-cycle contract cannot yet guarantee that an explicit non-schema prohibition or preservation
instruction reaches the restart-safe provider-neutral final artifact. The real catalog, deployment
composition, operational controls, language acceptance, migration rehearsal, and downstream
provider handoff also remain unapproved and unverified.
