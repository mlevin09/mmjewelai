# [V2] Implement Question Catalog v1

Read AGENTS.md, ARCHITECTURE.md and specs/questions/README.md on jewelai-v2. Branch from and target PRs to jewelai-v2.

## Dependencies
Jewelry Design Schema, Role Profiles, Domain Dictionary.

## Acceptance criteria
A question owns a stable semantic ID, canonical schema target, answer contract, role/locale wording, examples and artifact version.
Rules decide when to ask; wording must not hide executable selection logic.
Initial semantic examples: CENTER_STONE_SHAPE, CENTER_STONE_DIMENSIONS, CENTER_STONE_SETTING, METAL_COLOR, SIDE_STONE_QUANTITY.
These examples are not a complete production catalog.

Provide six role variants or a documented deterministic fallback. Unknown role/locale behavior must be explicit.
Validate field references, answer types, dictionary references and duplicate IDs at load time.
Deliver catalog schema, reviewed seed entries and loader.
Tests cover rendering for six roles, missing translations, invalid references and preservation of semantic intent.

## Definition of done
- [ ] Versioned contract and scoped implementation.
- [ ] Meaningful positive/negative tests, documented run command.
- [ ] Cross-references validated and domain-review decisions explicit.
- [ ] PR and updated specifications; preserve V1 files.

Exclude frontend, image generation, provider calls, persistence and infrastructure.
