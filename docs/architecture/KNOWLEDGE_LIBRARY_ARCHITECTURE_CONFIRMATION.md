# Knowledge Library architecture confirmation

Status: **CONFIRMED_WITH_DEFERRALS**  
Decision date: 2026-10-03  
Production ACTIVE: **false**

## Scope

This record closes the architecture-validation phase for the JewelAI Knowledge Library and records
the evidence used to freeze Contract v1.0.0. It does not claim production parser, matcher, policy
execution, Matrix Engine integration or ACTIVE catalogs.

## Gate result

| Gate | Criterion | Result |
| --- | --- | --- |
| A | Canonical chain needs no structural redesign | PASS |
| B | New concepts are additive | PASS |
| C | RU/EN share language-neutral canonical IDs | PASS |
| D | Domain facts and JewelAI policy are separated | PASS |
| E | Provenance is traceable | PASS with note |
| F | Applicability, ambiguity, recommendation, assumption and preservation are explicit | PASS |
| G | Reference compiler integrity passes | PASS |
| H | Architecture works beyond solitaire | PASS with required refinement |
| I | No open HIGH architectural defect | PASS |
| J | Remaining gaps are closed or isolated | PASS with deferrals |

The validated canonical chain is:

```text
SOURCE → CLAIM → DOMAIN KNOWLEDGE → LANGUAGE → JEWELAI POLICY → COMPILED RUNTIME → TEST
```

## Validation evidence

The solitaire reference package completed the Step 5 gate with:

- integrity: 12 PASS / 0 FAIL;
- semantic corpus: 38 PASS / 6 EXPECTED_GAP / 0 FAIL;
- 61 Claim records and 36 Source records with zero missing primary Claim → Source references;
- no production ACTIVE promotion.

The Step 6 three-stone stress test completed 12 architecture checks with zero failures after one
additive refinement: collection-scoped side-stone parameter templates keyed by stable `group_id`.

The current Jewelry Design Schema v1.0.0 already models `side_stones` as stable groups and explicitly
uses group IDs in concrete paths. The Rules Engine already expands `side_stones[*].quantity` across
existing groups. Therefore the stress-test refinement does not require a new architectural layer.

## Required contract refinement

Contract v1.0.0 includes collection-scoped templates:

```text
side_stones.{group_id}.stones.material
side_stones.{group_id}.stones.shape
side_stones.{group_id}.stones.cut
side_stones.{group_id}.stones.weight
side_stones.{group_id}.stones.dimensions
side_stones.{group_id}.stones.color
side_stones.{group_id}.stones.setting
side_stones.{group_id}.stones.orientation
side_stones.{group_id}.quantity
```

Runtime expansion binds only existing group IDs. Array indexes are not stable identifiers.

## Deferrals

- **AC-DEF-001:** generalized repeated-field runtime targeting beyond the current Rules v1 quantity
  expansion is production-integration work.
- **AC-DEF-002:** multi-focal designs without a unique center require a future explicit schema/domain
  decision and are outside the confirmed solitaire + three-stone slice.
- **AC-DEF-003:** corroborative-only evidence must be represented explicitly, rather than treated as
  an unused primary source.

These deferrals do not change the canonical chain and do not leave an open HIGH architectural defect.

## Consequence

The architecture is confirmed and may be used as the basis for the frozen Knowledge Library Contract
v1.0.0. Production implementation must validate against that contract and may not treat architecture
confirmation as an ACTIVE promotion.
