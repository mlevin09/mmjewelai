# JewelAI Decision Log

Status: Working

## Policy

This log records only material, durable, explicitly recorded team decisions that affect product direction, architecture, cross-product contracts, security/data policy, commercial structure, material operational policy, or another durable project constraint.

Routine implementation choices should remain in code, issues, pull requests, or technical documentation unless they create a durable project constraint.

The project has not yet introduced a formal approval lifecycle. Therefore this baseline does not retroactively label historical statements as Accepted decisions.

## Status vocabulary

- PROPOSED
- WORKING
- ACCEPTED — reserved for use after an explicit approval process is defined and applied
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

The following are governance conventions introduced by this baseline and remain Working until the team defines its approval process:

### GOV-W01 — No implicit Accepted status

Existing project documents, specifications, architecture material, benchmarks, roadmaps, presentations, and research are not Accepted solely because they exist, appear mature, or are currently used.

### GOV-W02 — Product priority remains open

No existing JewelAI product is treated as the first development priority, primary product, or default entry point without an explicit recorded team decision.

### GOV-W03 — GitHub governance is canonical

The version-controlled files under `docs/governance/` are the canonical governance copy. Project Sources/Drive may provide a readable mirror or knowledge layer. If a mirror differs, the repository version governs.

### GOV-W04 — Live systems retain operational authority

`CURRENT_STATE.md` summarizes and links current state but does not replace the repository, GitHub issues/PRs, deployment configuration, infrastructure state, or other live operational systems.
