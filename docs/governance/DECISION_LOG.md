# JewelAI Decision Log

Status: Working
Last reviewed: 2026-09-27

## Policy

This log records material, durable, explicitly recorded team decisions affecting product direction, cross-product architecture, security/data policy, commercial structure, material operational policy, governance, or another durable project constraint.

Routine implementation choices remain in code, issues, pull requests, ADRs, or technical documentation unless they create a durable project-level constraint.

Repository ADRs keep their own statuses.

## Status vocabulary

- PROPOSED
- WORKING
- ACCEPTED — use for Project-level decisions only after explicit approval authority/action is defined
- REJECTED
- SUPERSEDED
- DEPRECATED
- HISTORICAL / NEEDS CONFIRMATION

## Working governance conventions

### GOV-W01 — No implicit Project-document acceptance

Drive/Project documents, specifications, benchmarks, roadmaps, presentations, and research are not Accepted solely because they exist, appear mature, or are currently used.

Repository records with their own explicit lifecycle retain that status within their scope.

### GOV-W02 — Product priority remains open

No existing JewelAI product is treated as the first development priority, primary product, or default entry point without an explicit recorded team decision.

### GOV-W03 — GitHub governance is canonical

The version-controlled files under `docs/governance/` are the canonical governance copy.

Project Sources/Drive may provide a readable mirror or knowledge layer. If a mirror differs, the repository version governs.

### GOV-W04 — Live systems retain operational authority

`CURRENT_STATE.md` summarizes current state but does not replace the repository, GitHub issues/PRs, deployment configuration, infrastructure state, or other live operational systems.

### GOV-W05 — Historical MVP decisions are not auto-migrated

Decision cells in historical MVP planning artifacts remain historical evidence unless independently validated against current product strategy and explicitly recorded through the current decision process.

See `reviews/MVP_0_1_DECISION_REVIEW.md`.

### GOV-W06 — Vibe coding is the default development mode

Date: 2026-09-27
Status: WORKING
Scope: JewelAI software-development workflow

**Decision**

JewelAI software development should default to an action-oriented vibe-coding workflow.

For routine coding work, the agent should execute through repository inspection, implementation, validation, PR preparation, and requested merge/continuation without repeatedly asking for confirmation.

The agent should resolve technical facts from tools and the repository first, make small reversible assumptions when needed, and ask the user only for genuinely blocking choices, credentials/permissions, irreversible/destructive authorization, or unresolved materially different product behavior.

**Consequence**

Project Instructions and the `jewelai-dev-task` Skill should optimize for low-interruption execution while preserving security, source-of-truth discipline, and risk-proportional verification.
