# ADR 0004: Provider abstraction and measured cost controls

Status: Accepted. Date: 2026-09-20.

## Context
OpenAI/Gemini comparison should not couple domain logic to one vendor or add unnecessary A/B cost.

## Decision
Use a provider-neutral gateway with configured model IDs, timeouts, budgets and explicit fallback tracking.
Always validate specs/prompts deterministically. Later visual QA runs conditionally or on a recorded sample.
Defer mandatory CDN, dedicated vector DB and BigQuery until measured demand supports them.

## Alternatives
Direct provider calls from domain code hinder comparison. Paid visual QA on every image adds latency and cost.

## Consequences
Experiments need pinned versions, cost/latency metrics and fallback attribution. Optional visual QA cannot guarantee visual correctness.

## Validation
Gateway contract tests and experiment lineage checks belong to later integration issues.
