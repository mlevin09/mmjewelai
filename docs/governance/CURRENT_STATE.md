# JewelAI Current State

Status: Working
Last reviewed: 2026-09-27

> This file is a navigational snapshot, not a replacement for authoritative live systems. Verify volatile repository, CI/CD, deployment, infrastructure, provider, pricing, and external facts at the source when current accuracy matters.

## Executive state

JewelAI is being developed as an AI-native modular ecosystem for the jewelry industry.

Product prioritization remains open. No existing product is designated by this governance baseline as the first development priority, primary product, or default ecosystem entry point.

The Drive/Project knowledge corpus is still in a Working governance stage. No Drive/Project document is classified as Accepted by default.

Repository ADRs retain their own explicit engineering statuses. Several V2 ADRs are already marked `Accepted` inside the repository and remain authoritative within their technical scope.

## Active repository state

Repository: `mlevin09/mmjewelai`

Current V2 integration branch at review time:

- branch: `jewelai-v2`
- governance baseline merge commit: `89db1ca07087dc749c92ca2fcaab6e42b93117a5`\n- current head: verify live in GitHub when needed

PR #26 (`feat(infra): add production GCP deployment platform`) is merged into `jewelai-v2`.

The repository now contains implemented V2 foundations including the deterministic jewelry-domain contract, modular-monolith boundaries, persistence/API, parser/prompt/model-gateway boundaries, asset handling, authentication/organization membership, generation queue/worker flows, web/OIDC workflow, and production-platform infrastructure definitions.

For exact current implementation, verify the repository rather than relying on this summary.

## Production platform

Production infrastructure is described in Terraform and deployment workflows, but acceptance/merge of infrastructure code did not itself provision GCP/Auth0/DNS resources.

Actual production provisioning and operator prerequisites remain operational actions to be verified against the live environment.

## Governance work

Governance baseline was merged through PR #27 into `jewelai-v2` on 2026-09-27.

Core governance records:

- Project Context: Working
- Current State: Working
- Decision Log: Working
- Source Map: Working
- Glossary: Working

## Product state

Multiple JewelAI product concepts and modules exist in project documentation. Their existence or documentation maturity does not establish current development priority.

## Visualization state

Current visualization knowledge materials represent an evolving Working architecture.

`JewelAI_Vision_Core.pdf` is treated as the primary Working reference within visualization-core scope for the Project knowledge corpus, not as an Accepted project specification.

`JewelAI_Retail_Vision_Spec.pdf` is a primary Working reference within Retail visualization scope and does not imply Retail product priority.

Repository V2 implementation may contain technical decisions that are more current than these Drive documents for implemented runtime behavior.

## Benchmark state

Visualization benchmark methodology is Working.

`JewelAI_Visualization_Benchmark_Scenarios_v1.3.docx` has a filename/internal-version mismatch that should be corrected when that document is next revised.

## Customer discovery

`JewelAI_CustomerDiscovery_опросник.docx` is a primary Working reference for Customer Discovery methodology.

Hypotheses contained in research material remain hypotheses unless validated and explicitly recorded.

## External references

BLNG documentation is external reference material. It may inform JewelAI decisions but does not establish JewelAI requirements by itself.

Competitor reviews are evidence/reference material. `Обзор приложения jewelerstusio.ai.docx` is image-based (no extractable document text) and should be treated as visual competitor evidence rather than unreadable text.

## Historical MVP map review

The historical MVP spreadsheet contains 87 populated decision cells. These represent earlier planning choices, not current accepted product priorities.

A dedicated review classifies them against current V2 reality without retroactively migrating them into the Decision Log.

See `reviews/MVP_0_1_DECISION_REVIEW.md`.

## Remaining governance actions

- Merge/review PR #27 when the team is satisfied with the governance baseline.
- Mirror the merged canonical governance files into Project Sources/Drive.
- Define who may assign Project-level `Accepted` status before using that status for Drive/Project documents.
- Correct the visualization benchmark version mismatch when revising that source.
