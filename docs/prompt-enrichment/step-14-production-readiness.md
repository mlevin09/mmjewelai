# Prompt Enrichment Step 14 production-readiness foundation

Status: `IN_PROGRESS`
PR scope: 14A qualification foundation, 14B controlled runtime composition, 14C typed handoff,
and 14D evidence-driven release readiness
14D required baseline: `jewelai-v2` at `f1769bab181282fa6a9089a2bf89c666bb043656`;
review branch synchronized with subsequent reviewed catalog merges through
`5584c4b177a1bd9f11c268bc39ca8754144d6f93`

Step 13 remains `INTERNAL_VALIDATION_PASSED`. That evidence proves the controlled internal flow, not
production approval. Step 14A added a read-only qualification operation. Step 14B adds an explicit,
disabled-by-default application composition capability. Step 14C adds a read-only typed downstream
handoff. None activates a catalog, applies a migration, deploys, switches traffic, or authorizes
production use.

Step 14D adds readiness assessment contract `1.0.0`. It aggregates bounded evidence but cannot
output production `GO`: even `READY_FOR_APPROVAL` still requires a separately accountable decision.

## Qualification boundary

`qualify_knowledge_release()` accepts one explicit package/version selection, its immutable ACTIVE
envelope, its production-validation report, and the already configured `KnowledgeArtifactStore`.
It reuses:

- `ProductionValidationReport` and the six-category all-PASS gate from ADR 0028;
- `ActiveKnowledgeRuntime` identity and validation-report hash binding;
- `KnowledgeArtifactStore.load_active_runtime()` for source, runtime, manifest, checksum,
  deterministic-recompilation, exact-path, runtime-hash, report-hash, and ACTIVE-envelope checks;
- the frozen Knowledge Library contract and schema versions.

It returns qualification contract `1.0.0` evidence with candidate kind, exact release identity,
runtime SHA-256, validation-report SHA-256, gate status, loader-compatibility outcome, bounded
blocking reasons, optional source commit, and a deterministic qualification SHA-256. Wall-clock time
is intentionally not part of the canonical result: identical immutable inputs produce identical
evidence. An operator may timestamp the surrounding execution record without changing its content
identity.

Statuses have deliberately narrow meanings:

- `QUALIFIED`: the supplied candidate passed the existing ACTIVE gate and the actual durable runtime
  was loaded and verified. This does not activate or deploy it.
- `BLOCKED`: a candidate was selected but required evidence or runtime verification failed.
- `NOT_EVALUATED`: no candidate was supplied. This is never success.

Candidate kind is explicit. `SYNTHETIC` qualification tests the mechanism only.
`PRODUCTION_INTENDED` identifies operator intent but does not itself prove curation, approval,
activation, or deployment.

## Invocation and reproduction

```text
python -m jewelai_domain.knowledge_preflight \
  --artifact-root /durable/knowledge \
  --package-id jewelai.example.release \
  --artifact-version 1.0.0 \
  --active-release /reviewed/evidence/active.json \
  --validation-report /reviewed/evidence/validation-report.json \
  --source-commit <exact-reviewed-commit>
```

The preflight emits one canonical JSON result. It does not write that result or alter the artifact
root. Approved operational tooling may retain the JSON in an existing governed artifact system.
Google Drive remains an external mirror only and is never consulted as runtime source or fallback.

Run with only `--artifact-root` to produce explicit `NOT_EVALUATED` evidence when no candidate is
available. Supplying just one of package ID/version is rejected as an invalid invocation.

## Compatibility evidence and limitations

The production-validation report already binds the exact runtime to compiler/contract, provenance,
RU/EN matcher, runtime policy, Prompt Enrichment integration, and behavioral-regression evidence.
The preflight additionally proves that the exact durable runtime can pass the production loader.
Existing repository suites exercise the Matrix/Policy engine, recommendation non-acceptance,
explicit constraint preservation, final provider-neutral prompt assembly, and the three-stone stable
group slice. PR 14A does not reinterpret evidence references or invent a second validation gate.

The checked-in `jewelai.validation.three_stone` package is a synthetic validation slice. The later
merged `jewelai.production.jewelry_core` v1.0.0 source is an explicitly named production catalog
candidate, but it remains compiler state `COMPILED`/`active_for_production=false`; the repository
contains no corresponding governed ACTIVE envelope and production-validation report. Therefore the
actual production-candidate result at this baseline is `NOT_EVALUATED`. Actual qualification
requires all of:

1. a separately reviewed real catalog published under an immutable package ID/version;
2. its all-PASS six-category `ProductionValidationReport` with behavioral and three-stone evidence
   appropriate to the intended catalog;
3. the matching immutable `ActiveKnowledgeRuntime` envelope;
4. the durable artifact root containing the exact source/runtime/manifest/checksum set;
5. an exact reviewed source commit for the qualification execution record.

Synthetic unit and compatibility tests must never be relabeled as those inputs.

## Controlled application composition

`RuntimeSettings.prompt_enrichment` is `None` by default. In that state `create_app()` does not call
the qualifier or durable loader, does not construct `PromptEnrichmentRuntimeService`, and does not
register any of the five `/v1/sessions/{session_id}/prompt-enrichment/*` routes. They are also absent
from OpenAPI. Existing legacy routes, Google Text Intake, provider adapters, workers, and generation
behavior are unchanged.

When `PROMPT_ENRICHMENT_ENABLED` is exactly `true`, all of these settings are mandatory:

- `PROMPT_ENRICHMENT_KNOWLEDGE_ARTIFACT_ROOT`
- `PROMPT_ENRICHMENT_KNOWLEDGE_PACKAGE_ID`
- `PROMPT_ENRICHMENT_KNOWLEDGE_ARTIFACT_VERSION`
- `PROMPT_ENRICHMENT_ACTIVE_RELEASE_PATH`
- `PROMPT_ENRICHMENT_VALIDATION_REPORT_PATH`
- `PROMPT_ENRICHMENT_QUALIFICATION_CONTRACT_VERSION` (currently exactly `1.0.0`)
- `PROMPT_ENRICHMENT_CANDIDATE_KIND` (`SYNTHETIC` or `PRODUCTION_INTENDED`)

The existing `ROLE_ARTIFACT_VERSION`, `DICTIONARY_ARTIFACT_VERSION`,
`QUESTION_ARTIFACT_VERSION`, `RULES_ARTIFACT_VERSION`, and `PROMPT_ARTIFACT_VERSION` pins remain the
non-Knowledge runtime selections. Enabled composition reads the two configured governed evidence
files, uses `KnowledgeArtifactStore` at the exact configured root, calls
`qualify_knowledge_release()`, requires `QUALIFIED`, and constructs the existing
`PromptEnrichmentRuntimeService`. The qualifier in turn uses the actual durable runtime loader, so
source, runtime, manifest, checksums, deterministic recompilation, package/version, runtime hash,
validation-report hash, ACTIVE state, and the six-category all-PASS gate are all verified before
routes exist.

There is no `latest`, current-release alias, wildcard, discovery scan, or Google Drive fallback.
An enabled incomplete configuration fails during settings construction. Missing/corrupt evidence or
a blocked/tampered release fails startup with a bounded configuration error; it does not silently
disable the module or expose a partial router. An internally created database engine is disposed if
controlled composition fails. Repeated application construction owns independent repositories and
services and creates no global mutable release state.

### Synthetic nonproduction example

The following names illustrate controlled test composition only. They are not a production
activation command and do not describe an approved real catalog:

```text
PROMPT_ENRICHMENT_ENABLED=true
PROMPT_ENRICHMENT_KNOWLEDGE_ARTIFACT_ROOT=/test-fixtures/knowledge
PROMPT_ENRICHMENT_KNOWLEDGE_PACKAGE_ID=jewelai.validation.three_stone
PROMPT_ENRICHMENT_KNOWLEDGE_ARTIFACT_VERSION=1.0.0
PROMPT_ENRICHMENT_ACTIVE_RELEASE_PATH=/test-fixtures/evidence/active.json
PROMPT_ENRICHMENT_VALIDATION_REPORT_PATH=/test-fixtures/evidence/validation-report.json
PROMPT_ENRICHMENT_QUALIFICATION_CONTRACT_VERSION=1.0.0
PROMPT_ENRICHMENT_CANDIDATE_KIND=SYNTHETIC
```

`SYNTHETIC` is rejected when `JEWELAI_ENVIRONMENT=production`. Conversely, labeling a candidate
`PRODUCTION_INTENDED` records intent only; it is not human approval, activation, deployment, or a
go-live decision. The checked-in production candidate still lacks governed ACTIVE and validation
evidence and has not been submitted to the qualifier by this work.

### Pinning, authorization, and rollback

The selected release supplied to the service is the release written into the existing session pin
on the first enrichment cycle. Restart with the same selection restores exact package/version and
hash lineage. Restart under a different configured release does not migrate an existing session;
the existing repository pin and integrity checks reject the mismatch. Current single-release-per-app
composition remains explicit rather than adding unapproved multi-release orchestration.

The controlled endpoints retain the existing bearer authentication, current membership checks,
organization/session repository scope, CAS, locks, durable clarification plans, correction history,
constraint evidence, and provider-neutral Internal Final Prompt. Disabling the feature again means
setting `PROMPT_ENRICHMENT_ENABLED=false` or omitting it and restarting the application. That removes
only route composition and never deletes append-only history.

PostgreSQL migration head remains `0014_clarification_plans`. No background task, release cache,
provider handoff, deployment setting, or production route enablement is added by Step 14B.

## Typed downstream handoff

`InternalFinalPromptHandoff` v1.0.0 is the provider-neutral Step 14C boundary. It embeds the exact
validated `InternalFinalPrompt` v1.1.0 and binds it to organization/session scope, current Product
State revision, latest authoritative enrichment cycle, exact pinned Knowledge package/version and
runtime/report hashes, prompt schema/hash, existing readiness, and a deterministic handoff hash.
The embedded prompt remains the single semantic payload: accepted decisions, active prohibitions
and preservation instructions, full constraint supersession history, unresolved ambiguity, and
unaccepted recommendation evidence are neither translated nor copied into competing fields.

`PromptEnrichmentRuntimeService.build_current_internal_final_prompt_handoff()` is an internal
callable only. It first restores the existing current organization-scoped durable state and
revalidates the pinned ACTIVE runtime, revision/cycle alignment, artifact versions, clarification
and correction lineage, constraint evidence, and final-prompt hash. The handoff builder then
revalidates the complete final output before binding its envelope. Missing, cross-organization,
stale, mismatched, or tampered history fails closed through the existing bounded runtime errors.

Construction is read-only: it writes no IDs or timestamps, creates no cycles or decisions, and is
deterministic across repeated calls, concurrent readers, and runtime restart. A later correction
produces different revision, cycle, prompt, and handoff hashes; constructing the current handoff
therefore cannot silently return the historical object.

Existing readiness semantics are preserved. `ready` and `ready_with_unresolved` are eligible for
later downstream provider-specific preparation; `blocked` is not. Eligibility is not generation
authorization. Step 14C adds no public endpoint, provider translation, task publication, Model
Gateway request, worker invocation, catalog activation, or fallback. The legacy `CompiledPrompt`
pipeline and all existing frontend generation actions remain untouched.

## Step 14D readiness assessment contract

`PromptEnrichmentReleaseReadinessAssessment` v1.0.0 is a read-only application-level evidence
envelope. It records the exact 40-character source commit, Knowledge qualification identity and
hashes when present, runtime-composition contract `1.0.0`, `InternalFinalPrompt` `1.1.0`, handoff
`1.0.0`, migration head, all gates in canonical order, bounded reasons, and a canonical evidence
SHA-256. Operational timestamps belong in the surrounding execution record and cannot change the
assessment hash.

The deterministic policy is:

- any verified mandatory failure produces `BLOCKED` and missing evidence is retained;
- otherwise any unevaluated mandatory gate produces `NOT_EVALUATED`;
- otherwise the technical result is `READY_FOR_APPROVAL`;
- the operational-approval gate is recorded but deliberately cannot turn technical evidence into an
  automatic deployment permission.

The four Knowledge gates are derived from the existing `KnowledgeReleaseQualification`; callers
cannot self-assert them. A blocked qualification fails those gates. A qualified `SYNTHETIC`
candidate remains `NOT_EVALUATED` for real-catalog readiness. Only an exact qualified
`PRODUCTION_INTENDED` candidate can pass them, and that classification still is not human approval.

The CLI consumes trusted local evidence and is non-mutating:

```text
python -m jewelai_api.prompt_enrichment_readiness \
  --source-commit <exact-40-character-reviewed-commit> \
  --migration-head 0014_clarification_plans \
  --qualification /reviewed/evidence/qualification.json \
  --gates /reviewed/evidence/non-knowledge-gates.json
```

`--gates` contains every non-Knowledge gate exactly once in enum order. Passing evidence requires a
non-secret reference and direct-verification flag. Omit `--qualification` only to record the real
catalog as explicitly unevaluated. Exit codes are `0` for `READY_FOR_APPROVAL`, `1` for `BLOCKED`,
and `2` for `NOT_EVALUATED`. The command does not write evidence, activate a release, change
configuration, call a provider, or deploy anything.

## Evidence inventory at the 14D baseline

| Item | Directly observed state | Classification |
|---|---|---|
| Knowledge candidates | Synthetic three-stone and `jewelai.production.jewelry_core` v1.0.0 source are checked in | Verified directly |
| Governed real catalog | Production source candidate exists but remains non-ACTIVE and unevaluated by the release qualifier | Available, not qualified |
| ACTIVE envelope/report | Test helpers construct synthetic evidence; no real governed files are present | Real evidence missing |
| Six-category validation | Existing synthetic three-stone report and tests pass all categories | Synthetic only |
| Durable runtime | Filesystem store/compiler/loader/checksum/recompilation are tested | Synthetic only |
| Runtime composition | Complete exact-release configuration is required and tested | Synthetic only |
| Preproduction | Isolated `mmjewellai-preprod` services exist; API revision observed as `jewelai-preprod-api-00011-cnp` | Available, inspected read-only |
| Preproduction feature state | API environment-variable names contain no `PROMPT_ENRICHMENT_*` configuration | Verified disabled |
| Migration chain | Repository head is `0014_clarification_plans`; Runtime API CI upgrades PostgreSQL | Disposable CI evidence |
| Local disposable PostgreSQL | No local PostgreSQL URL or Docker daemon was available during implementation | Not accessible locally |
| Rollback | Immutable-image rollback and no-automatic-downgrade guidance exists in `infra/RUNBOOK.md` | Procedure exists; rehearsal missing |
| Authentication/isolation | Bearer membership and cross-organization tests cover controlled routes | Synthetic integration evidence |
| Observability | Generic Cloud Run request/latency/5xx, uptime, and generation-failure controls exist | Prompt Enrichment signals not verified in preprod |
| Handoff | Typed v1.0.0 handoff is merged and tested; no provider consumes it | Verified internal only |
| Approval | No accountable Step 14 release decision is recorded | Missing |

The real release status is therefore `REAL_CATALOG_NOT_EVALUATED`. The isolated preproduction
environment is available, but no authorization in this PR enables the controlled module or writes
test data. Synthetic evidence cannot change either result.

## Release acceptance matrix

This matrix describes the evidence actually available at the 14D baseline, not a rollout claim.

| Gate | Status | Evidence | Kind / direct | Blocking reason and follow-up |
|---|---|---|---|---|
| Source integrity | PASS | exact baseline and merged PR CI | Real / yes | Re-run CI on this PR head |
| Real catalog | NOT_EVALUATED | production candidate source inventory | Real candidate / yes | Create governed validation/ACTIVE evidence and explicitly qualify it |
| Knowledge validation | NOT_EVALUATED | synthetic qualification tests only | Synthetic / yes | Produce real six-category PASS report |
| ACTIVE integrity | NOT_EVALUATED | synthetic envelope tests only | Synthetic / yes | Provide matching real envelope/report/runtime hashes |
| Durable storage | NOT_EVALUATED | synthetic filesystem release only | Synthetic / yes | Publish exact reviewed real artifacts to governed storage |
| Runtime composition | PASS | composition startup/tamper tests | Synthetic / yes | Repeat with real qualified release in preprod |
| Default isolation | PASS | route/OpenAPI absence tests and preprod env-name inspection | Real + synthetic / yes | Preserve disabled default |
| Migration rehearsal | PASS | fresh PostgreSQL CI upgrade/check/current | Disposable real PostgreSQL / yes | Retain CI evidence for exact release head |
| Rollback rehearsal | NOT_EVALUATED | runbook procedure and disablement tests | Synthetic / partial | Rehearse immutable-image rollback and feature disablement in preprod |
| Authentication | PASS | bearer, membership, scope tests | Synthetic / yes | Repeat bounded authorized preprod checks |
| Semantic correctness | PASS | EN/RU/mixed full-cycle tests | Synthetic / yes | Validate intended real catalog language coverage |
| Constraint preservation | PASS | prohibition/preservation/supersession tests | Synthetic / yes | Repeat exact real release acceptance corpus |
| Final prompt | PASS | authoritative v1.1.0 integrity tests | Synthetic / yes | No provider handoff authorization implied |
| Handoff | PASS | v1.0.0 scope/hash/readiness/restart tests | Synthetic / yes | Keep provider-neutral boundary |
| Legacy isolation | PASS | disabled/enabled composition regression tests | Synthetic / yes | Confirm on preprod deployment candidate |
| Observability | NOT_EVALUATED | generic platform signals only | Real / partial | Verify bounded module-specific failure classifications in preprod |
| Operational approval | NOT_EVALUATED | none | None / yes | Named owner records explicit decision after technical evidence |

Because mandatory real-catalog, rollback, and observability evidence is missing, the actual aggregate
result is `NOT_EVALUATED`, not `READY_FOR_APPROVAL` and never `GO`.

## Migration and rollback rehearsal

The safe disposable-database rehearsal is:

1. create an isolated empty PostgreSQL database and set `TEST_POSTGRES_URL` and the Alembic URL to
   that database only;
2. run `alembic -c packages/persistence/alembic.ini upgrade head`, `check`, and `current`;
3. require `0014_clarification_plans (head)` and run the PostgreSQL persistence/concurrency suites;
4. where an approved pre-0014 fixture exists, restore it into another disposable database and
   upgrade forward; do not manufacture unknown historical data;
5. discard the databases after retaining non-sensitive command/status evidence.

Migration 0014 is additive but existing pre-0014 enrichment cycles have no durable plan and continue
to fail closed. There is no automatic reconstruction. A database downgrade is not the default
rollback: record prior immutable image digests, disable Prompt Enrichment composition, roll the
application back only to a schema-compatible image, preserve append-only module history, and use
backup restoration only under the existing incident procedure. Rehearsal must separately record
application rollback, feature disablement, configuration rollback, database compatibility, and data
restoration. No destructive downgrade is authorized by this document.

Disablement is restart-scoped: remove or set `PROMPT_ENRICHMENT_ENABLED=false`, restart the API, and
verify the five controlled routes and OpenAPI entries are absent. Product State, release pins,
cycles, clarification/correction evidence, and legacy generation records must remain unchanged.

## Security and observability acceptance

Mandatory security evidence includes bearer verification, current organization membership,
organization-scoped session lookups, server-selected release identity, exact qualified hashes,
bounded startup/runtime errors, no external-mirror fallback, and rejection of client-controlled
paths or ACTIVE evidence. Test evidence exists for these boundaries; deployed preproduction
verification remains outstanding. Evidence and logs must never contain credentials, raw prompts,
customer assets, or untrusted filesystem paths.

Existing platform signals cover Cloud Run request counts, latency, 5xx responses, uptime, database
connectivity, and legacy generation failures. The rehearsal must also prove safe classification for
startup qualification failure, missing/tampered artifacts, invalid durable history, stale revisions,
clarification/correction conflicts, release-pin conflicts, and unexpected controlled-route
availability. These module-specific signals have not been verified in preproduction, so the
observability gate remains `NOT_EVALUATED`; this PR does not introduce another monitoring platform.

## End-to-end and handoff acceptance

The existing deterministic suites exercise EN, RU, and bounded mixed-language input; explicit
`no halo` / `без гало`, `without engraving`, and `keep the original band`; recommendation
non-acceptance; accepted clarification; correction supersession; optional unresolved and mandatory
blocking states; restart restoration; organization scope; stale revisions; and tampered release and
constraint evidence. Assertions inspect the structured Product State, constraint evidence, final
prompt, and handoff rather than only status codes or hashes.

A blocked `InternalFinalPrompt` never becomes downstream-eligible. `ready_with_unresolved` follows
the existing contract and may be prepared downstream, but the handoff itself never authorizes a
provider, queue, worker, or generation call. Current deterministic parsing remains intentionally
narrow and does not promise arbitrary Russian morphology.

## PostgreSQL concurrency finding

The first PR #97 Runtime API attempt exposed a real `READ COMMITTED` snapshot race, not a legitimate
`INVALID_HISTORY` outcome. `list_clarification_answers()` first loaded the session and then loaded
answers in a second statement. A concurrent answer could commit between them, leaving an old
`current_revision_id` beside the newly visible answer and falsely reporting that the answer was not
in current Product State lineage.

The 14D correction reads the scoped session and its answer rows in one joined SQL statement, so both
come from one PostgreSQL statement snapshot. The same correction applies to the single-answer read.
A PostgreSQL regression deliberately commits an answer after the reader statement starts but before
its result is consumed; the reader sees a coherent pre-commit snapshot and the next read sees the
complete commit. `INVALID_HISTORY` remains reserved for actual corrupted/inconsistent history and is
not added to accepted concurrency outcomes.

## Release decision record template

```text
Release identity: <package-id>/<artifact-version>/<runtime-sha256>
Source commit: <exact-commit>
Technical readiness result: <READY_FOR_APPROVAL|BLOCKED|NOT_EVALUATED>
Canonical evidence hash: <sha256>
Evidence references: <governed references>
Known limitations: <explicit list>
Rollback plan reference: <reviewed runbook/rehearsal>
Required approvals: <roles or policy>
Explicit decision: <leave blank until authorized>
Decision owner: <leave blank until authorized>
Decision date: <leave blank until authorized>
Approval record reference: <leave blank until authorized>
```

Approval fields intentionally remain blank in repository documentation.

## Remaining rollout sequence

1. **PR 14A — Release qualification and preflight (this scope).** Read-only and fail-closed.
2. **PR 14B — Controlled runtime composition (this scope).** Disabled-by-default application
   composition for an exact qualified release; no implicit latest selection or live enablement.
3. **PR 14C — Downstream Internal Final Prompt handoff (this scope).** A typed provider-neutral
   adapter boundary without silently replacing legacy `CompiledPrompt` behavior.
4. **PR 14D — Readiness framework and rehearsal procedure (this scope).** Deterministic aggregation,
   evidence inventory, migration/rollback procedures, concurrency correction, and acceptance matrix.
5. **Authorized preproduction rehearsal.** Qualify a governed real catalog, enable the controlled
   runtime in isolation, execute the documented checks, and record an accountable decision.

Step 14 must remain `IN_PROGRESS` until those separately reviewed milestones and a real catalog
qualification are complete.
