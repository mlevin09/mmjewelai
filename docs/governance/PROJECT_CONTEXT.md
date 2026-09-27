# JewelAI Project Context

Status: Working
Governance maturity: Working; no project source is Accepted unless explicitly recorded through a future approval process.

## Purpose

JewelAI is an AI-native modular ecosystem for the jewelry industry. It is intended to support multiple specialized products, professional roles, organizations, and workflows.

Guiding principle:

**Shared core, specialized products, composable user experience.**

No existing product is assumed to be the first development priority, primary product, or default ecosystem entry point unless an explicit recorded team decision establishes that priority.

## Shared Core

Shared capabilities should emerge from demonstrated cross-product requirements or a clear architectural reason. Shared does not imply centralized deployment, one runtime service, or shared persistence.

## AI principle

JewelAI is multi-model and provider-flexible. Model/provider substitutability should be preserved at boundaries where switching, routing, benchmarking, resilience, cost control, or product independence creates material value.

## Governance

This directory contains the durable project governance layer:

- `PROJECT_CONTEXT.md` — stable orientation and governance rules.
- `CURRENT_STATE.md` — navigational snapshot of what is true now.
- `DECISION_LOG.md` — durable, material, explicitly recorded team decisions.
- `SOURCE_MAP.md` — classification, scope, status, and working authority of important sources.
- `GLOSSARY.md` — canonical project terminology.

## Source discipline

Project sources may include working specifications, drafts, research, benchmarks, historical implementations, presentations, external references, hypotheses, and superseded material. Presence in project sources does not make content current or authoritative.

Authority and freshness are separate dimensions. A newer source is not automatically more authoritative, and a historically authoritative source is not automatically current.

Until an explicit approval lifecycle is introduced and applied, existing JewelAI materials must not be labeled Accepted merely because they are mature or actively used.

## Live systems

Where a live system is authoritative, governance links to it rather than replacing it:

- current implementation: repository and merged code;
- tests/runtime behavior: verified test and runtime evidence;
- issues and pull requests: GitHub;
- deployments/infrastructure: actual deployment and infrastructure configuration;
- durable architecture decisions: ADRs when present;
- material team decisions: Decision Log.

Chat history provides context; durable records preserve project truth.
