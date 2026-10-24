# Prompt Enrichment Step 14 production-readiness foundation

Status: `IN_PROGRESS`
PR scope: 14A qualification foundation, 14B controlled runtime composition, and 14C typed handoff
14B baseline: `jewelai-v2` at `e34cee7c06369c91182de339c249ccbff9a2a9cd`

Step 13 remains `INTERNAL_VALIDATION_PASSED`. That evidence proves the controlled internal flow, not
production approval. Step 14A added a read-only qualification operation. Step 14B adds an explicit,
disabled-by-default application composition capability. Step 14C adds a read-only typed downstream
handoff. None activates a catalog, applies a migration, deploys, switches traffic, or authorizes
production use.

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

The checked-in `jewelai.validation.three_stone` package is a synthetic validation slice. It is not a
reviewed production-intended release, and the repository contains no corresponding governed real
ACTIVE envelope and production-validation report. Therefore the actual production-candidate result
at this baseline is `NOT_EVALUATED`. Actual qualification requires all of:

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
go-live decision. The repository still contains no real governed production-intended catalog.

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

## Remaining rollout sequence

1. **PR 14A — Release qualification and preflight (this scope).** Read-only and fail-closed.
2. **PR 14B — Controlled runtime composition (this scope).** Disabled-by-default application
   composition for an exact qualified release; no implicit latest selection or live enablement.
3. **PR 14C — Downstream Internal Final Prompt handoff (this scope).** A typed provider-neutral
   adapter boundary without silently replacing legacy `CompiledPrompt` behavior.
4. **PR 14D — Preproduction rehearsal and release acceptance.** Migration and rollback rehearsal,
   real-catalog verification, observability/security checks, end-to-end acceptance, and an explicit
   readiness decision.

Step 14 must remain `IN_PROGRESS` until those separately reviewed milestones and a real catalog
qualification are complete.
