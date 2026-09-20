# Jewelry Design Schema v1 — implementation brief

Define a versioned canonical schema plus Python domain models, independent of API/DB/providers.
Cover jewelry type, metal, center stone, side stone groups, construction, style, references and visual constraints.
Separate gemstone material from shape/cut; stone quantity must state scope (per side/per item/per pair).
Represent optional/inapplicable fields distinctly from unanswered required fields.

Each field carries value, origin (explicit/derived/assumed/unknown), confirmation, independent lock, provenance and applicable uncertainty.
Reject negative measurements/counts, invalid units and inconsistent state. Define explicit unlock/reconfirm transitions.
Support immutable revisions and reject stale or locked edits. Do not invent dimensions from weight alone.

Deliver JSON Schema, Python models, valid/invalid fixtures, compatibility/version policy and tests.
Acceptance: round-trip serialization; unknown/absent/not-applicable semantics; positive unit validation; locked conflict; derived source trace; per-side counts.
