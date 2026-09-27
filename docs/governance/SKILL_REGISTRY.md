# JewelAI Skill Registry

Status: Working
Last reviewed: 2026-09-27

Skills are repeatable workflow instructions. They do not replace Project Instructions, governance records, repository ADRs/specifications, or current source verification.

## Initial skill set

| Skill | Purpose | Default behavior |
|---|---|---|
| `jewelai-dev-task` | Repository implementation workflow | Vibe-coding optimized: execute with minimal interruption; repository first |
| `jewelai-release-readiness` | Release/deployment gates | Verify exact SHA/environment/infrastructure; ask only when authorization or target is genuinely blocked |
| `jewelai-visualization-benchmark` | Jewelry visualization model evaluation | Preserve test metadata and compare like-for-like |
| `jewelai-product-decision` | Product discovery/decision workflow | Separate evidence, hypothesis, recommendation, and decision |

## Governance rules

- Keep Skills procedural and lightweight.
- Do not copy the project knowledge base into a Skill.
- For coding tasks, consult the current repository first.
- Consult Project Sources only when product/domain intent, governance, or a task-specific source is needed.
- Resolve missing technical facts using tools before asking the user.
- Prefer small reversible assumptions over non-blocking clarification.
- A Skill-generated recommendation is not a team decision.
- Keep volatile model/provider names, branch heads, pricing, and deployment state out of Skill instructions unless required as an invariant.

## Vibe-coding rule

The `jewelai-dev-task` Skill is the primary coding Skill and should optimize for continuous execution.

It should not create routine approval gates, "human review" gates, or confirmation loops.

Questions are reserved for real blockers: unavailable credentials/permissions, destructive authorization, unresolved materially different product behavior, or an unsafe/unknown target environment.
