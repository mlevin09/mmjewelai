# JewelAI Skill Registry

Status: Working
Last reviewed: 2026-09-27

Skills are repeatable workflow instructions. They do not replace Project Instructions, governance records, repository ADRs/specifications, or current source verification.

## Initial skill set

| Skill | Purpose | Trigger examples | Source-of-truth behavior |
|---|---|---|---|
| `jewelai-dev-task` | Repository implementation workflow | implement issue, fix bug, prepare PR, change schema/API | Verify GitHub/current architecture first |
| `jewelai-release-readiness` | Release/deployment gates | first production deploy, Terraform plan/apply, release readiness | Verify exact SHA, environment, credentials, infrastructure and runtime |
| `jewelai-visualization-benchmark` | Jewelry visualization model evaluation | compare image models, controlled edits, multi-turn benchmark | Preserve model/version/config/date/scenario and cost per successful scenario |
| `jewelai-product-decision` | Product discovery/decision workflow | evaluate product concept, feature, segment, experiment | Separate evidence, interpretation, hypothesis, recommendation and decision |

## Governance rules

- Keep skills procedural and lightweight; do not copy the project knowledge base into a skill.
- Skills must consult current Project Sources/repository when the task depends on JewelAI-specific facts.
- A skill-generated recommendation is not a team decision.
- Update a skill when the repeatable workflow changes materially, not for every project-state change.
- Keep model/provider names, branch heads, pricing, deployment state and other volatile facts out of skill instructions unless the workflow itself requires a fixed invariant.
- Review skill behavior against current Project Instructions after material governance changes.

## Distribution

Each skill is packaged independently as `skill.zip` so it can be installed or updated separately.

The canonical governance repository records the skill purpose and workflow expectation; the installable archives are maintained outside the repository unless the team intentionally chooses to version binary skill packages.
