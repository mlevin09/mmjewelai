# Jewelry Design Schema v1.1.0 runtime

Status: **implemented additive runtime contract; not the default persisted API schema**.

Schema v1.1.0 extends the immutable v1.0.0 design snapshot with the Product State
ownership frozen in P0-16. The Python contract is
`jewelai_domain.models_v1_1.DesignRevisionV1_1`; the JSON Schema exporter is
`jewelai_domain.schema_v1_1.json_schema_v1_1`.

## Compatibility

- v1.0.0 remains a valid immutable historical contract.
- v1.1.0 is additive and rejects unknown fields.
- `upgrade_design_revision_v1_to_v1_1()` is explicit and never fills new fields.
- Existing revision IDs, parent lineage, timestamps, provenance, confirmation and
  locks are preserved by the additive upgrade.
- New fields require their own evidence/state and are not inferred from content
  availability.

Reference Binding and Visualization Verification remain separate contracts and are
not fields of `DesignV1_1`.

The frozen Product State target registry is
[target-registry-v1.1.0.json](target-registry-v1.1.0.json). The ownership/migration
contract is [contract-v1.1.0.json](contract-v1.1.0.json).
