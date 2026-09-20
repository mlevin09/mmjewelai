# [V2] Implement Role Profiles v1

Read AGENTS.md, ARCHITECTURE.md and specs/roles/README.md on jewelai-v2. Branch from and target PRs to jewelai-v2.

## Dependencies
Jewelry Design Schema.

## Acceptance criteria
Canonical IDs: retail_client, sales_manager, buyer, marketing, jewelry_designer, industrial_designer.
Profile fields: stable ID/version, expertise, vocabulary policy, detail level, question budget policy, allowed default/derivation policy and locale fallback.
Conversational roles grant no authorization.
All profiles share one schema and engine; role policies cannot bypass locked constraints.

Retail wording is plain language; industrial wording supports exact dimensions and construction.
Exact budgets/defaults are product-review decisions, not fabricated constants.
Deliver validated profile schema, six initial reviewed profiles and loader; reject duplicate/unknown IDs and invalid policies.
Tests cover every role, deterministic fallback and absence of privilege/lock bypass.

## Definition of done
- [ ] Versioned contract and scoped implementation.
- [ ] Meaningful positive/negative tests, documented run command.
- [ ] Cross-references validated and domain-review decisions explicit.
- [ ] PR and updated specifications; preserve V1 files.

Exclude frontend, image generation, provider calls, persistence and infrastructure.
