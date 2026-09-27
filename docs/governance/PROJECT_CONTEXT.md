# JewelAI Project Context

Status: Working
Last reviewed: 2026-09-27

## Purpose

JewelAI is an AI-native modular ecosystem for the jewelry industry. It is intended to support multiple specialized products, professional roles, organizations, and workflows.

Guiding principle:

**Shared core, specialized products, composable user experience.**

No existing product is assumed to be the first development priority, primary product, or default ecosystem entry point unless an explicit recorded team decision establishes that priority.

## Shared Core

Shared capabilities should emerge from demonstrated cross-product requirements or a clear architectural reason.

**Shared does not imply centralized deployment, one runtime service, or shared persistence.**

A shared capability may be expressed as a domain model, package, contract, service, knowledge asset, integration boundary, infrastructure component, or another reusable mechanism appropriate to the requirement.

## AI principle

JewelAI is multi-model and provider-flexible. Model/provider substitutability should be preserved at boundaries where switching, routing, benchmarking, resilience, cost control, or product independence creates material value.

Do not create provider abstraction solely for theoretical purity.

## Governance layer

The core durable governance records are:

- `PROJECT_CONTEXT.md` — stable orientation and governance rules.
- `CURRENT_STATE.md` — navigational snapshot of what is true now.
- `DECISION_LOG.md` — durable, material, explicitly recorded team decisions.
- `SOURCE_MAP.md` — classification, scope, status, and working authority of important sources.
- `GLOSSARY.md` — canonical project terminology.\n- `PROJECT_INSTRUCTIONS.md` — canonical text for the ChatGPT Project Instructions field.\n- `SKILL_REGISTRY.md` — registry and governance rules for reusable JewelAI Skills.

Supporting governance artifacts may be stored under `docs/governance/reviews/` or other clearly named subdirectories without expanding the core record set.

## Source discipline

Project knowledge sources may include working specifications, drafts, research, benchmarks, historical implementations, presentations, external references, hypotheses, and superseded material. Presence in Project Sources does not make content current or authoritative.

**Authority and freshness are separate dimensions.** A newer source is not automatically more authoritative, and a historically authoritative source is not automatically current.

The current Drive/Project knowledge corpus is in a Working stage. No Drive/Project document should be labeled Accepted merely because it is mature or actively used.

Repository ADRs and other repository-controlled records may have their own explicit status (including `Accepted`) under the engineering process. Governance must preserve those statuses rather than overwrite them.

## Working document lifecycle

For the Project knowledge corpus, use these statuses unless a source has its own authoritative lifecycle:

- `Draft` — incomplete and not yet the primary working reference.
- `Working` — active material used and evolved by the team.
- `Under Review` — intentionally being reviewed for a future formal decision.
- `Historical` — describes an earlier project state.
- `Superseded` — explicitly replaced in whole or in part.
- `Archived` — retained for record/history and not part of normal working context.
- `External Reference` — third-party/vendor material.

`Accepted` for Project knowledge is reserved until the team defines approval authority and applies an explicit approval action. Do not infer acceptance from usage, maturity, or file age.

## Live systems and authority

Where a live system is authoritative, governance links to it rather than replacing it:

- current implementation: merged repository state;
- tests/runtime behavior: verified test and runtime evidence;
- issues and pull requests: GitHub;
- deployments/infrastructure: actual deployment and infrastructure configuration;
- durable engineering architecture decisions: repository ADRs;
- material project-level decisions: Decision Log when explicitly recorded.

`CURRENT_STATE.md` is a navigation snapshot, not a competing source of truth.

Chat history provides context; durable records preserve project truth.

## Governance mirroring

Canonical governance lives in version control under `docs/governance/`.

A Drive/Project Sources copy may be maintained as a readable knowledge mirror. When mirroring:

1. mirror only from a reviewed repository commit;
2. retain the same filename and content;
3. record the source branch/commit and mirror date in the mirrored copy or accompanying index;
4. do not edit the mirror as the authoritative source;
5. if repository and mirror differ, the repository governance copy governs;
6. refresh the mirror after material governance changes.

Until automated synchronization exists, mirroring is a manual operational step.
