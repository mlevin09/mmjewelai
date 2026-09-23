# ADR 0006: Establish the modular-monolith repository layout

Status: Accepted. Date: 2026-09-23.

## Context
JewelAI V2 has an implemented deterministic domain contract in `packages/domain`, while the rest of the runtime is intentionally not implemented yet.
The architecture baseline already names future API, web, prompt, model-gateway, worker, infrastructure, and repository-level test boundaries.
A tracked repository skeleton is needed so subsequent issues have stable ownership locations without moving or rewriting the preserved V1 root files.

## Decision
Establish the following tracked modular-monolith skeleton:

- `apps/api`
- `apps/web`
- `packages/domain` (existing implementation, unchanged)
- `packages/prompts`
- `packages/model_gateway`
- `workers/generation`
- `infra`
- `tests`

Existing `data`, `specs`, and `docs` directories remain the homes for reviewed catalogs, versioned contracts, and architecture/product documentation.
New runtime boundaries are documentation-only placeholders until their dedicated implementation issues are approved.
The V1 root `README.md`, `Dockerfile`, `docker-compose.yml`, and root Python packaging are not migrated or reinterpreted by this step.

Dependency direction is inward: applications and workers may depend on reusable packages; reusable domain packages must not depend on applications or workers.
Provider adapters, persistence, authentication, queueing, frontend frameworks, and cloud resources are explicitly out of scope for this structural step.

## Alternatives
Create all runtime Python/JavaScript packages now: rejected because it would select frameworks and dependencies before their implementation issues.
Move the preserved V1 root files into a legacy directory: rejected because V1 preservation and migration require a separate explicit change.
Leave the layout implicit until each component is implemented: rejected because it invites inconsistent locations and cross-component coupling.

## Consequences
Future issues have stable locations and clearer ownership boundaries without claiming unimplemented runtime behavior.
The repository temporarily contains placeholder README files in runtime locations.
Root V1 packaging remains misleading if read without the repository audit, so contributors must continue to follow `AGENTS.md` and `docs/architecture/REPOSITORY_AUDIT.md`.
No dependencies, provider integrations, database code, frontend code, or infrastructure resources are added by this decision.

## Validation
Verify all declared directories are tracked, confirm `packages/domain` is unchanged, and run the existing domain test suite.
At acceptance, the 81 pre-existing domain tests must still pass.
