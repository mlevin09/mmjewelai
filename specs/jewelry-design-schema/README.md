# Jewelry Design Schema v1.0.0

Issue #1 contract, implemented in [packages/domain](../../packages/domain/README.md).
The [JSON Schema](schema.json) describes a complete DesignRevision wire snapshot.
[Fixtures](fixtures/README.md) contain synthetic examples and deliberate errors.

## Coverage and boundaries

Design contains jewelry_type, metal, center_stone, side_stones, construction, style, references and
visual_constraints. Material, shape and cut are distinct fields. Domain identifiers are stable lower
snake case strings; actual dictionary membership, supported jewelry families and domain terminology
remain for Issue #3 and domain review. The schema does not claim manufacturing feasibility.

Lengths use positive finite mm; gemstone weights use positive finite ct. Metal purity uses either
karat (0 < value <= 24) or integer fineness (1..1000). Stone counts are positive integers with mandatory
scope: per_side, per_item or per_pair. Zero is represented by no side-stone group, not a group of zero
stones. No carat-to-dimension inference is performed. Dimensions describe length, width and depth.

## Field state

| Representation | Meaning and evidence |
| --- | --- |
| Omitted/null field | Not collected; no assertion of known, optional, required or inapplicable |
| Unknown | Explicitly unanswered; requirement is required, optional or undetermined; no value, confirmation or lock |
| NotApplicable | Explicit declaration with reason and source message; confirmed, optionally locked |
| Explicit | Value with source message ID and timestamp |
| Derived | Value with one or more versioned KB/rule sources and an uncertainty description |
| Assumed | Value with versioned rule source and a disclosed rationale |

An absent field is preserved semantically as null in a normalized snapshot; omission versus literal
null is not a separate state. Unknown(required) is distinct from Unknown(optional), an absent field,
and NotApplicable. The later Rules Engine sets/validates requiredness and decides whether an
inapplicability declaration is acceptable; partial intake snapshots are deliberately valid here.

Known values have independent confirmed and locked booleans. A lock requires confirmation;
confirming a derived/assumed value never erases its origin or evidence. A confirmed assumption remains
an assumption. Explicit data is not automatically confirmed. Composite values (dimensions, references,
style lists and visual constraint lists) share one provenance/lock at the field boundary.

## Immutability, edits and lineage

DesignRevision requires schema_version, design_id, unique revision_id, positive revision number,
timezone-aware created_at, event and design. Revision 1 has no parent and a create event. Later
revisions have a parent and a non-create event. Parent cannot equal self; event source time cannot
be after revision time. IDs are UUIDs; message/asset IDs are opaque text references.

All nested models are frozen and collections are tuples. Normal APIs do not mutate previous states.
Validate untrusted JSON with DesignRevision.model_validate_json. Do not use Pydantic model_construct
or model_copy(update=...) as validation/update APIs; standard Python escape hatches are not a security
boundary. Public transition functions and snapshot_json revalidate inputs.

- revise_design accepts an unconfirmed replacement design and preserves every locked leaf, including
  locks inside removed/rekeyed groups. New/changed values must be unconfirmed and unlocked. Explicit
  NotApplicable declarations are the sourced exception to confirmation, but cannot introduce a lock.
- confirm_field confirms an existing value, retaining its source and origin.
- lock_field locks only a confirmed, unlocked value.
- unlock_field records the explicit reason/source and leaves confirmation intact until the value
  changes. The next edit must clear confirmation, then be reconfirmed before relocking.

Paths use model field names, e.g. metal.color or side_stones.accents.quantity, where accents is the
stable group_id, never an array position. IDs must be unique within a design. Each transition creates
a new UUID and increments the revision, retaining design_id and recording parent, source and reason.
Every operation checks expected_revision_id. A no-op edit and backwards timestamps are rejected.

The caller must load the current authoritative revision. A future repository must atomically compare
and swap its stored token; no database concurrency guarantee or actor authorization is implemented here.

## Validation layers

JSON Schema draft 2020-12 handles wire shapes, state alternatives, required provenance, supported
unit tags, ranges, unknown properties, lock/confirmation invariant and basic revision-parent rules.
Enable format validation for date-time and UUID when using a standalone validator.
Python also rejects nonfinite numbers, duplicate group IDs, self-parent IDs and inconsistent time
ordering. Revision functions enforce locks and stale-token checks relative to the prior snapshot.
Neither JSON Schema nor a standalone snapshot can establish historical authorization or readiness.

## Compatibility and verification

schema_version is mandatory and exactly 1.0.0; unsupported versions and extra properties fail closed.
Artifacts are immutable after release. Changing fields, enum meaning, units or transitions incompatibly
requires a major version and explicit migration. Additive changes require a new minor contract and
updated consumers because older validators reject unknown properties. Documentation-only corrections
may use a patch release. Never silently migrate a historical snapshot or replace its source versions.

Regenerate schema.json using the documented exporter, review the diff, and run package tests and lint.
The tests compare the committed schema with generated output, validate shared fixtures independently,
and exercise transition/semantic rules. Pydantic upgrades that change generated schema require review.
See [ADR 0005](../../docs/adr/0005-domain-contract-revisions.md) for the design decision.
