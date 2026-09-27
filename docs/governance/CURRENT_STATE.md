# JewelAI Current State

Status: Working
Last reviewed: 2026-09-27

> Navigational snapshot only. Verify volatile repository, CI/CD, deployment, infrastructure, provider, pricing, and external facts at the source.

## Executive state

JewelAI is being developed as an AI-native modular ecosystem for the jewelry industry.

Product prioritization remains open. No existing product is designated as the first development priority, primary product, or default ecosystem entry point.

Repository ADRs retain their own explicit engineering statuses.

## Development mode

As of 2026-09-27, JewelAI development uses **vibe coding as the default software-development workflow**.

The desired agent behavior is:
- execute rather than repeatedly ask for routine confirmation;
- verify repository/tool state directly;
- use small reversible assumptions for non-blocking uncertainty;
- inspect only relevant sources first;
- continue through implementation, tests, PR, and requested merge/next step;
- ask only for genuine blockers, secrets/permissions, destructive authorization, or unresolved materially different product behavior.

## Active repository state

Repository: `mlevin09/mmjewelai`

Current V2 integration branch:
- `jewelai-v2`
- current head: verify live in GitHub when needed

The repository contains implemented V2 foundations including deterministic jewelry-domain contracts, modular-monolith boundaries, persistence/API, parser/prompt/model-gateway boundaries, asset handling, authentication/organization membership, generation queue/worker flows, web/OIDC workflow, and production-platform infrastructure definitions.

## Production platform

Production infrastructure is described in Terraform and deployment workflows, but merged infrastructure code does not itself prove that GCP/Auth0/DNS resources are provisioned.

Actual production state must be verified against the live environment.

## ChatGPT Project configuration

Project Instructions, governance sources, and four JewelAI Skills are installed.

For routine coding, the optimized rule is now:
**repository first; Project Sources only when product/domain intent or governance is actually needed.**

Installed Skills:
- `jewelai-dev-task`
- `jewelai-release-readiness`
- `jewelai-visualization-benchmark`
- `jewelai-product-decision`

GitHub `docs/governance/` remains canonical; Project Sources are a readable knowledge mirror.

## Product state

Multiple JewelAI product concepts and modules exist in project documentation. Their existence or documentation maturity does not establish current development priority.

## Visualization state

`JewelAI_Vision_Core.pdf` is a primary Working reference within visualization-core scope.

`JewelAI_Retail_Vision_Spec.pdf` is a primary Working reference within Retail visualization scope and does not imply Retail product priority.

Repository V2 implementation may be more current than Drive documents for implemented runtime behavior.

## Benchmark state

Visualization benchmark methodology is Working.

`JewelAI_Visualization_Benchmark_Scenarios_v1.3.docx` has a filename/internal-version mismatch to correct when next revised.

## Customer discovery

`JewelAI_CustomerDiscovery_опросник.docx` is a primary Working methodology reference.

## Historical MVP map review

The historical MVP spreadsheet contains 87 populated decision cells. They remain historical planning evidence unless explicitly revisited.

See `reviews/MVP_0_1_DECISION_REVIEW.md`.

## Remaining governance actions

- Replace the current ChatGPT Project Instructions with the vibe-coding optimized canonical version.
- Reinstall/update `jewelai-dev-task` with the vibe-coding optimized Skill package.
- Refresh this Current State mirror in Project Sources after those changes.
- Define who may assign Project-level `Accepted` status.
