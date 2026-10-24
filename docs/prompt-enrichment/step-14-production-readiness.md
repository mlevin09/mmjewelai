# Prompt Enrichment Step 14 production-readiness foundation

Status: `IN_PROGRESS`
PR scope: 14A — release qualification and preflight
Baseline: `jewelai-v2` at `3524d4181f9db60286cfd6b543de402e62cf813d`

Step 13 remains `INTERNAL_VALIDATION_PASSED`. That evidence proves the controlled internal flow, not
production approval. Step 14A adds a read-only qualification operation and does not compose the
controlled router, activate a catalog, apply a migration, deploy, or switch traffic.

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

## Future production configuration inventory

Current production composition has no Knowledge Library release-selection settings and does not
inject `PromptEnrichmentRuntimeService` into `create_app()`. No environment-variable names are
invented by this PR.

Future controlled composition must explicitly provide the durable artifact root, exact package ID
and artifact version, governed ACTIVE envelope and validation report, and the already pinned
dictionary/question/rules/prompt artifact versions. It must retain organization-scoped HTTP
authorization, PostgreSQL migration head `0014_clarification_plans`, fail-closed loader errors,
structured non-secret observability, and a composition-only rollback that omits the controlled
router without deleting append-only history. Existing identity, database, provider credentials,
generation profiles, Model Gateway, workers, and provider-neutral `InternalFinalPrompt` handoff stay
separate.

## Remaining rollout sequence

1. **PR 14A — Release qualification and preflight (this scope).** Read-only and fail-closed.
2. **PR 14B — Controlled runtime composition.** Disabled-by-default deployment composition for an
   exact already-qualified release; no implicit latest selection.
3. **PR 14C — Downstream Internal Final Prompt handoff.** A typed provider-neutral adapter boundary
   without silently replacing legacy `CompiledPrompt` behavior.
4. **PR 14D — Preproduction rehearsal and release acceptance.** Migration and rollback rehearsal,
   real-catalog verification, observability/security checks, end-to-end acceptance, and an explicit
   readiness decision.

Step 14 must remain `IN_PROGRESS` until those separately reviewed milestones and a real catalog
qualification are complete.
