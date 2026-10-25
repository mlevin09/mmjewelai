# P0-19 Schema v1.1 Consumer Coverage & Controlled Adoption

Status: **IMPLEMENTED — MERGE GATED BY FULL CI**  
Date: **2026-10-25**

## Purpose

P0-19 moves Jewelry Design Schema v1.1 from persistence-only support to controlled
runtime adoption without pretending that every additive field has bespoke intake
semantics.

The key distinction is:

- **preservation coverage** — a consumer can carry a v1.1 field through its workflow
  without dropping or rewriting it;
- **direct interaction coverage** — a consumer can explicitly parse, ask about, or
  apply deterministic rules to that field.

## Consumer coverage contract

`consumer_coverage_v1_1.py` publishes a deterministic coverage report for the
complete frozen `PRODUCT_STATE_TARGET_FAMILIES_V1_1` registry.

All frozen v1.1 Product State target families are required to have preservation
coverage through Product State traversal, Knowledge runtime, and prompt compilation.

Direct semantic coverage remains intentionally narrower:

- Parser direct targets: the existing supported v1 intake targets;
- Question direct targets: the five existing semantic Question Catalog targets;
- Rules direct targets: the same five deterministic Rules v1 targets.

No target is reported as directly supported merely because the schema can store it.

## Controlled migration

The API now exposes:

- `GET /sessions/{session_id}/schema-v1-1-eligibility`
- `POST /sessions/{session_id}/schema-v1-1-upgrade`

Migration remains explicit and compare-and-swap guarded. It appends a new immutable
v1.1 revision and keeps the historical v1.0 snapshot unchanged.

A session already on v1.1 is not migration-eligible again.

New sessions continue to start on v1.0.0. There is no bulk migration and no
automatic migration during reads, edits, or deployment.


### Runtime compatibility gate

Prompt Enrichment remains a v1.0-only consumer chain in P0-19. When that runtime
service is configured, migration eligibility is explicitly blocked with
`PROMPT_ENRICHMENT_RUNTIME_V1_1_UNSUPPORTED`.

This prevents a session from being migrated into a state that the configured
clarification / enrichment / correction workflow cannot safely consume. P0-19 does
not partially upgrade that chain or silently bypass the blocker.

## Parser adoption

Parser Proposal v1 remains a bounded input vocabulary. It is now revision-version
aware:

- v1.0 revisions produce v1.0 proposed designs;
- v1.1 revisions produce v1.1 proposed designs;
- existing supported parser edits preserve all unmentioned additive v1.1 state.

P0-19 does not claim that the Parser can directly extract all additive v1.1 fields.

## Rules and Questions adoption

Rules v1 now accepts either Design Revision v1.0 or v1.1 while evaluating the same
five frozen deterministic targets. Question Catalog v1 remains unchanged and
continues to render the same five semantic questions.

This is deliberate compatibility, not a silent expansion of domain policy.

## Revision transition boundary

Parser-authored v1.1 edits use a narrow v1.1 transition that accepts only a design
already produced by the trusted Parser Proposal boundary.

Generic user-supplied v1.1 revision mutation is not added in this step. The existing
generic revision transition API therefore remains a v1.0 contract until a separate
versioned transition contract is implemented.

## Explicit non-goals

P0-19 does not:

- make Schema v1.1 the default for new sessions;
- claim 118+ bespoke parser/question/rule interactions;
- activate a new Knowledge Library release in production;
- add provider/model behavior;
- migrate production or preproduction sessions;
- change deployment infrastructure.

## Exit gate

P0-19 is complete only when the feature branch passes the repository Domain, Runtime
API, Parser, Prompt, Knowledge regression, Ruff, and Web workflows against the
current `jewelai-v2` baseline.
