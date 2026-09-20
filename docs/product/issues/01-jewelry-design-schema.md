# [V2] Implement Jewelry Design Schema v1

Read AGENTS.md, ARCHITECTURE.md and specs/jewelry-design-schema/README.md on jewelai-v2. Branch from and target PRs to jewelai-v2.

## Dependencies
None. First foundation issue.

## Acceptance criteria
Define a versioned canonical schema plus Python domain models, independent of API/DB/providers.
Cover jewelry type, metal, center stone, side stone groups, construction, style, references and visual constraints.
Separate gemstone material from shape/cut; stone quantity must state scope (per side/per item/per pair).
Represent optional/inapplicable fields distinctly from unanswered required fields.

Each field carries value, origin (explicit/derived/assumed/unknown), confirmation, independent lock, provenance and applicable uncertainty.
Reject negative measurements/counts, invalid units and inconsistent state. Define explicit unlock/reconfirm transitions.
Support immutable revisions and reject stale or locked edits. Do not invent dimensions from weight alone.

Deliver JSON Schema, Python models, valid/invalid fixtures, compatibility/version policy and tests.
Acceptance: round-trip serialization; unknown/absent/not-applicable semantics; positive unit validation; locked conflict; derived source trace; per-side counts.

## Definition of done
- [ ] Versioned contract and scoped implementation.
- [ ] Meaningful positive/negative tests, documented run command.
- [ ] Cross-references validated and domain-review decisions explicit.
- [ ] PR and updated specifications; preserve V1 files.

Exclude frontend, image generation, provider calls, persistence and infrastructure.
