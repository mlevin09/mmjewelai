# JewelAI Decision Log

Status: Working
Last reviewed: 2026-09-27

## Policy

This log records only material, durable, explicitly recorded team decisions that affect product direction, architecture across product boundaries, security/data policy, commercial structure, material operational policy, governance, or another durable project constraint.

Routine implementation choices should remain in code, issues, pull requests, ADRs, or technical documentation unless they create a durable project-level constraint.

The Project knowledge corpus has not yet introduced a formal approval lifecycle. Therefore this log does not retroactively label historical Drive/Project statements as Accepted decisions.

Repository ADRs keep their own statuses. An ADR marked `Accepted` in the repository is an accepted engineering decision within its stated scope and does not need to be copied into this log merely to preserve that status.

## Status vocabulary

- PROPOSED
- WORKING
- ACCEPTED — use for Project-level decisions only after explicit approval authority/action is defined
- REJECTED
- SUPERSEDED
- DEPRECATED
- HISTORICAL / NEEDS CONFIRMATION

## Decision record template

### DEC-XXX — Title

Date:
Status:
Scope:

**Decision**

[Explicit decision.]

**Context**

[Why the decision is needed.]

**Rationale**

[Evidence and reasoning.]

**Alternatives considered**

[Material alternatives, if relevant.]

**Consequences**

[Important consequences and constraints.]

**Related sources**

[Links to specifications, ADRs, issues, PRs, research, or other evidence.]

**Supersedes**

[Decision ID or none.]

**Superseded by**

[Decision ID or none.]

---

## Working governance conventions

These conventions describe the current Working governance baseline. They are not labeled Accepted until the team defines Project-level approval authority.

### GOV-W01 — No implicit Project-document acceptance

Drive/Project documents, specifications, benchmarks, roadmaps, presentations, and research are not Accepted solely because they exist, appear mature, or are currently used.

Repository records with their own explicit lifecycle (for example an ADR marked `Accepted`) retain that status within their scope.

### GOV-W02 — Product priority remains open

No existing JewelAI product is treated as the first development priority, primary product, or default entry point without an explicit recorded team decision.

### GOV-W03 — GitHub governance is canonical

The version-controlled files under `docs/governance/` are the canonical governance copy.

Project Sources/Drive may provide a readable mirror or knowledge layer. If a mirror differs, the repository version governs.

### GOV-W04 — Live systems retain operational authority

`CURRENT_STATE.md` summarizes and links current state but does not replace the repository, GitHub issues/PRs, deployment configuration, infrastructure state, or other live operational systems.

### GOV-W05 — Historical MVP decisions are not auto-migrated

Decision cells in historical MVP planning artifacts remain historical evidence unless independently validated against current product strategy and explicitly recorded through the current decision process.

See `reviews/MVP_0_1_DECISION_REVIEW.md`.
