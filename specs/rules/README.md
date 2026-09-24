# Rules Engine v1.0.0

Issue #5 contract, implemented by `jewelai_domain.rules` in
[packages/domain](../../packages/domain/README.md). The [JSON Schema](schema.json) describes the
declarative artifact, and [data/rules/v1.0.0.json](../../data/rules/v1.0.0.json) contains nine proposed
seed rules.

## Boundary and inputs

The engine accepts a validated immutable `DesignRevision`, canonical role, pinned Role Profile,
Dictionary, Question Catalog and Rules artifacts, optional `AvailableKnowledgeFact` values, and an
optional `ProposedDomainUpdate` used for the bounded locked-metal conflict scenario. It returns one
immutable typed decision: `ask`, `derive`, `assume`, `block`, or `ready`.

The engine never changes the revision. Derived and assumed values are proposals only; callers must
use the existing revision transitions to persist, confirm, or lock them. Rules grant no authorization
and cannot unlock a field or bypass stale-revision checks.

Catalog JSON is data interpreted by fixed Python code. There is no `eval`, `exec`, Python snippet,
JSONPath/JMESPath, regex program, generic property traversal, recursion over input data, LLM/provider
call, network call, persistence, or prompt wording in selection.

## Allowlisted vocabulary

Conditions are limited to:

- `target_state`: one bounded target is absent, unknown, unsatisfied, or satisfied.
- `role_is`: role equals one canonical Role ID.
- `role_derivation_mode`: profile uses one known derivation mode.
- `compatible_knowledge_fact`: a compatible supplied dimensions fact exists or does not exist.
- `locked_update_conflict`: the explicit metal-color proposal conflicts with its locked state.
- `field_equals`: one dictionary-backed target equals a reviewed canonical Domain ID.
- `all_required_targets_satisfied`: every concrete target in the v1 requiredness scope is satisfied.

Actions are `ask`, `derive`, `assume`, `block`, and `ready`. Ask actions reference Question Catalog
semantic IDs only. Derive is restricted in v1 to `center_stone.dimensions` and must consume an
explicit compatible fact. Assume is structurally supported with a canonical dictionary ID,
`RuleSource`, stable recorded time, and rationale, but the seed contains zero assumption rules because
Role Profiles require `ask_before_assume` and `no_unapproved_defaults`.

Every rule contains a stable lower-snake-case ID, semantic version, numeric priority, globally unique
tie order, optional bounded dependencies, target, conditions, action, stable reason code and text, and
provenance/review state. Unknown fields and vocabulary fail closed.

## Gap analysis and targets

The analyzer inspects exactly the five Question Catalog targets. It reports the generic target,
concrete target, absent/unknown/unsatisfied/satisfied state, requirement flag, confirmation and lock
status, question ID, and side-stone group ID where applicable.

`side_stones[*].quantity` expands only across existing groups. Concrete paths use
`side_stones.<group_id>.quantity`; groups are sorted lexically by stable `group_id`. The evaluator does
not interpret arbitrary paths or add a group. With no side-stone group, this collection requirement is
vacuously satisfied.

## Proposed v1 requiredness and readiness

The proposed seed treats these as required:

1. `center_stone.shape`
2. `center_stone.dimensions`
3. `center_stone.setting`
4. `metal.color`
5. `side_stones[*].quantity` for every existing side-stone group

Only these targets affect v1 readiness. Other Schema fields remain outside this deliberately narrow
policy; their absence does not keep a design incomplete. `NotApplicable` is unsatisfied for these
required targets. `ready` is emitted only when every concrete required target has a known Schema v1
value. This policy is proposed and requires product/jewelry review.

## Determinism, conflicts, and bounded evaluation

Rules sort by descending numeric priority, ascending globally unique `tie_order`, then rule ID as a
defensive stable key. Side-stone groups sort by group ID. Supplied matching facts sort by Knowledge
Source record ID and version. Artifact insertion order therefore has no effect.

Dependencies are checked by a catalog-size-bounded topological pass at load time; unknown references
and cycles fail. Evaluation performs one condition pass and one dependency pass. There is no iterative
revision mutation. Identical inputs and pinned artifacts produce model-equal, byte-stable decisions
and traces with no generated timestamps or UUIDs.

If applicable rules at the highest priority propose different actions for the same concrete target,
the engine returns `block` with `RULE_CONFLICT` and all involved rule IDs. Identical static conditions
with incompatible same-priority actions fail earlier at catalog load. Duplicate tie order also fails.

The seed precedence is: locked metal conflict (1000), shape gap (900), exact/derived/unsourced
dimensions (800), setting (700), metal color (600), side-stone quantity (500), ready (0). Mutually
exclusive role/fact conditions separate the three dimensions actions.

## Sourced fact and derivation boundary

`AvailableKnowledgeFact` is transient evaluator input, not a Knowledge Base. It contains a
`Dimensions` value, existing versioned `KnowledgeSource`, uncertainty, and exact match context for
jewelry type, center-stone material, and center-stone `Weight`. Context IDs are checked against the
pinned Dictionary. A fact matches only when all three context values equal known design values.

The match contract does not infer dimensions from weight. It accepts an already sourced value supplied
by a caller. No supplied compatible source means no `Derived` state. A derived proposal preserves the
Knowledge Source and uncertainty and is always unconfirmed and unlocked. Industrial designers use
`request_exact_when_required`, so they are asked for dimensions even when an estimate is supplied.

Final derivation eligibility, evidence quality thresholds, factual matching criteria, manufacturing
constraints, and a persistent Knowledge Base remain unresolved and out of scope.

## Trace and versioning

Each decision includes action, target/concrete target, question where applicable, rule ID and version,
rules artifact version, stable reason code/text, priority, tie order, optional proposed change, and a
trace of every rule in evaluation order. Condition traces contain a boolean outcome, stable detail,
and relevant Knowledge Source IDs.

Rules v1 pins Schema, Role Profiles, Domain Dictionary and Question Catalog artifacts at `1.0.0`.
Supplying mismatched registries fails at load. Published artifacts are immutable; policy changes need
a new artifact version and incompatible contract changes need a new major schema version.

## Review status and limitations

The entire seed is `proposed_pending_domain_review`. Final mandatory/optional fields, approved
assumptions, derivation evidence thresholds, KB matching, manufacturing constraints, and complete
domain-specific readiness remain open. No seed default, exact question budget, gemstone dimensional
fact, or production manufacturing rule is asserted.

## Verification

From the repository root in Python 3.12+:

```sh
python -m pip install -e './packages/domain[test]'
python -m pytest -c packages/domain/pyproject.toml packages/domain/tests/test_rules.py -q
python -m pytest -c packages/domain/pyproject.toml packages/domain/tests -q
python -m ruff check packages/domain
python -m ruff format --check packages/domain
```

Re-export the schema after an intentional contract change and review the diff:

```sh
python -m jewelai_domain.rules_schema specs/rules/schema.json
```
