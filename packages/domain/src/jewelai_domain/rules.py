"""Bounded declarative rules, gap analysis, and deterministic decisions."""

import json
from collections.abc import Iterator, Mapping
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from .dictionary import DictionaryCategory, DictionaryRegistry, ReviewStatus
from .models import (
    SCHEMA_VERSION,
    Assumed,
    Derived,
    DesignRevision,
    Dimensions,
    DomainId,
    ImmutableModel,
    KnowledgeSource,
    KnownValue,
    RuleSource,
    Text,
    Unknown,
    Version,
    Weight,
)
from .questions import QuestionCatalog, QuestionId, SchemaTarget
from .roles import DerivationMode, RoleId, RoleRegistry

RULES_SCHEMA_VERSION = "1.0.0"
RuleId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,79}$")]
Priority = Annotated[int, Field(strict=True, ge=0, le=10_000)]
TieOrder = Annotated[int, Field(strict=True, ge=0, le=10_000)]


class GapState(StrEnum):
    ABSENT = "absent"
    UNKNOWN = "unknown"
    UNSATISFIED = "unsatisfied"
    SATISFIED = "satisfied"


class ActionKind(StrEnum):
    ASK = "ask"
    DERIVE = "derive"
    ASSUME = "assume"
    BLOCK = "block"
    READY = "ready"


class ReasonCode(StrEnum):
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    EXACT_MEASUREMENT_REQUIRED = "EXACT_MEASUREMENT_REQUIRED"
    SOURCED_DERIVATION_AVAILABLE = "SOURCED_DERIVATION_AVAILABLE"
    NO_VALID_KB_MATCH = "NO_VALID_KB_MATCH"
    LOCKED_FIELD_CONFLICT = "LOCKED_FIELD_CONFLICT"
    ALL_REQUIRED_FIELDS_SATISFIED = "ALL_REQUIRED_FIELDS_SATISFIED"
    APPROVED_ASSUMPTION = "APPROVED_ASSUMPTION"
    RULE_CONFLICT = "RULE_CONFLICT"
    NO_VALID_DECISION = "NO_VALID_DECISION"


class TargetStateCondition(ImmutableModel):
    kind: Literal["target_state"] = "target_state"
    target: SchemaTarget
    states: tuple[GapState, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_states(self):
        if len(set(self.states)) != len(self.states):
            raise ValueError("Target states must be unique")
        return self


class RoleCondition(ImmutableModel):
    kind: Literal["role_is"] = "role_is"
    role_id: RoleId


class RoleDerivationCondition(ImmutableModel):
    kind: Literal["role_derivation_mode"] = "role_derivation_mode"
    mode: DerivationMode


class KnowledgeFactCondition(ImmutableModel):
    kind: Literal["compatible_knowledge_fact"] = "compatible_knowledge_fact"
    target: Literal[SchemaTarget.CENTER_STONE_DIMENSIONS]
    exists: bool


class LockedUpdateConflictCondition(ImmutableModel):
    kind: Literal["locked_update_conflict"] = "locked_update_conflict"
    target: Literal[SchemaTarget.METAL_COLOR]


class FieldEqualsCondition(ImmutableModel):
    kind: Literal["field_equals"] = "field_equals"
    target: Literal[
        SchemaTarget.CENTER_STONE_SHAPE,
        SchemaTarget.CENTER_STONE_SETTING,
        SchemaTarget.METAL_COLOR,
    ]
    value: DomainId
    dictionary_category: DictionaryCategory


class AllRequiredSatisfiedCondition(ImmutableModel):
    kind: Literal["all_required_targets_satisfied"] = "all_required_targets_satisfied"


RuleCondition = Annotated[
    TargetStateCondition
    | RoleCondition
    | RoleDerivationCondition
    | KnowledgeFactCondition
    | LockedUpdateConflictCondition
    | FieldEqualsCondition
    | AllRequiredSatisfiedCondition,
    Field(discriminator="kind"),
]


class AskAction(ImmutableModel):
    kind: Literal["ask"] = "ask"
    question_id: QuestionId


class DeriveAction(ImmutableModel):
    kind: Literal["derive"] = "derive"


class AssumeAction(ImmutableModel):
    kind: Literal["assume"] = "assume"
    value: DomainId
    dictionary_category: DictionaryCategory
    rationale: Text
    recorded_at: AwareDatetime


class BlockAction(ImmutableModel):
    kind: Literal["block"] = "block"


class ReadyAction(ImmutableModel):
    kind: Literal["ready"] = "ready"


RuleAction = Annotated[
    AskAction | DeriveAction | AssumeAction | BlockAction | ReadyAction,
    Field(discriminator="kind"),
]


class RuleProvenance(ImmutableModel):
    source_kind: Literal["repository_spec"] = "repository_spec"
    source_ref: Literal["docs/product/issues/05-rules.md"]
    review_status: ReviewStatus


class Rule(ImmutableModel):
    rule_id: RuleId
    rule_version: Version
    priority: Priority
    tie_order: TieOrder
    target: SchemaTarget | None
    conditions: tuple[RuleCondition, ...] = Field(min_length=1)
    action: RuleAction
    reason_code: ReasonCode
    reason: Text
    depends_on: tuple[RuleId, ...] = ()
    provenance: RuleProvenance

    @model_validator(mode="after")
    def validate_rule_shape(self):
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("Rule dependencies must be unique")
        if self.rule_id in self.depends_on:
            raise ValueError("A rule cannot depend on itself")
        if isinstance(self.action, ReadyAction):
            if self.target is not None:
                raise ValueError("A ready rule cannot target a field")
            if not any(isinstance(item, AllRequiredSatisfiedCondition) for item in self.conditions):
                raise ValueError("A ready rule requires all_required_targets_satisfied")
        elif self.target is None:
            raise ValueError("Non-ready rules require a target")

        for condition in self.conditions:
            if (
                isinstance(
                    condition,
                    (TargetStateCondition, KnowledgeFactCondition, LockedUpdateConflictCondition),
                )
                and condition.target != self.target
            ):
                raise ValueError("Target-specific conditions must match their rule target")
        if (
            isinstance(self.action, DeriveAction)
            and self.target != SchemaTarget.CENTER_STONE_DIMENSIONS
        ):
            raise ValueError("Rules v1 can derive only center-stone dimensions")
        if (
            isinstance(self.action, AssumeAction)
            and self.target not in _DICTIONARY_TARGET_CATEGORIES
        ):
            raise ValueError("Rules v1 assumptions require a dictionary-backed target")
        return self


class RulesBundle(ImmutableModel):
    schema_version: Literal["1.0.0"]
    artifact_version: Version
    design_schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    role_artifact_version: Version
    dictionary_artifact_version: Version
    question_artifact_version: Version
    review_status: Literal["proposed_pending_domain_review"]
    source: Literal["docs/product/issues/05-rules.md"]
    required_targets: tuple[SchemaTarget, ...]
    rules: tuple[Rule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bundle(self):
        if self.required_targets != tuple(SchemaTarget):
            raise ValueError("Rules v1 required targets must use the documented stable order")
        ids = [rule.rule_id for rule in self.rules]
        if len(set(ids)) != len(ids):
            raise ValueError("Rule IDs must be unique")
        ties = [rule.tie_order for rule in self.rules]
        if len(set(ties)) != len(ties):
            raise ValueError("Rule tie_order values must be globally unique")

        known = set(ids)
        for rule in self.rules:
            unknown = set(rule.depends_on) - known
            if unknown:
                raise ValueError(f"Unknown rule dependencies: {sorted(unknown)}")
        _dependency_order(self.rules)

        for index, left in enumerate(self.rules):
            for right in self.rules[index + 1 :]:
                if (
                    left.priority == right.priority
                    and left.target == right.target
                    and left.conditions == right.conditions
                    and left.action != right.action
                ):
                    raise ValueError(
                        f"Static rule conflict between {left.rule_id} and {right.rule_id}"
                    )
        if not any(isinstance(rule.action, ReadyAction) for rule in self.rules):
            raise ValueError("Rules v1 requires an explicit ready rule")
        for target in self.required_targets:
            if not any(
                rule.target == target
                and isinstance(rule.action, (AskAction, DeriveAction, AssumeAction))
                for rule in self.rules
            ):
                raise ValueError(f"Required target has no resolution rule: {target.value}")
        return self


_QUESTION_BY_TARGET = {
    SchemaTarget.CENTER_STONE_SHAPE: QuestionId.CENTER_STONE_SHAPE,
    SchemaTarget.CENTER_STONE_DIMENSIONS: QuestionId.CENTER_STONE_DIMENSIONS,
    SchemaTarget.CENTER_STONE_SETTING: QuestionId.CENTER_STONE_SETTING,
    SchemaTarget.METAL_COLOR: QuestionId.METAL_COLOR,
    SchemaTarget.SIDE_STONE_QUANTITY: QuestionId.SIDE_STONE_QUANTITY,
}

_DICTIONARY_TARGET_CATEGORIES = {
    SchemaTarget.CENTER_STONE_SHAPE: DictionaryCategory.STONE_SHAPE,
    SchemaTarget.CENTER_STONE_SETTING: DictionaryCategory.STONE_SETTING,
    SchemaTarget.METAL_COLOR: DictionaryCategory.METAL_COLOR,
}


def _dependency_order(rules: tuple[Rule, ...]) -> tuple[str, ...]:
    remaining = {rule.rule_id: set(rule.depends_on) for rule in rules}
    result: list[str] = []
    for _ in range(len(rules)):
        available = sorted(rule_id for rule_id, deps in remaining.items() if not deps)
        if not available:
            raise ValueError("Rule dependency graph contains a cycle")
        for rule_id in available:
            result.append(rule_id)
            del remaining[rule_id]
            for dependencies in remaining.values():
                dependencies.discard(rule_id)
        if not remaining:
            return tuple(result)
    raise ValueError("Rule dependency evaluation exceeded the catalog-size bound")


class Gap(ImmutableModel):
    target: SchemaTarget
    concrete_target: Text
    state: GapState
    required: bool
    confirmed: bool
    locked: bool
    group_id: DomainId | None = None
    question_id: QuestionId


class KnowledgeMatchContext(ImmutableModel):
    jewelry_type: DomainId
    center_stone_material: DomainId
    center_stone_weight: Weight


class AvailableKnowledgeFact(ImmutableModel):
    target: Literal[SchemaTarget.CENTER_STONE_DIMENSIONS]
    value: Dimensions
    source: KnowledgeSource
    uncertainty: Text
    match: KnowledgeMatchContext


class ProposedDomainUpdate(ImmutableModel):
    """Minimal explicit update input used only for the v1 locked-metal conflict check."""

    target: Literal[SchemaTarget.METAL_COLOR]
    value: DomainId


class ConditionTrace(ImmutableModel):
    condition_kind: Text
    outcome: bool
    detail: Text
    source_ids: tuple[Text, ...] = ()


class RuleTrace(ImmutableModel):
    rule_id: RuleId
    priority: Priority
    tie_order: TieOrder
    target: SchemaTarget | None
    concrete_target: Text | None
    action_considered: ActionKind
    conditions: tuple[ConditionTrace, ...]
    applicable: bool
    selected: bool


class ProposedDerivedChange(ImmutableModel):
    kind: Literal["derived"] = "derived"
    target: Literal[SchemaTarget.CENTER_STONE_DIMENSIONS]
    concrete_target: Literal["center_stone.dimensions"]
    state: Derived[Dimensions]


class ProposedAssumedChange(ImmutableModel):
    kind: Literal["assumed"] = "assumed"
    target: Literal[
        SchemaTarget.CENTER_STONE_SHAPE,
        SchemaTarget.CENTER_STONE_SETTING,
        SchemaTarget.METAL_COLOR,
    ]
    concrete_target: Text
    state: Assumed[DomainId]


class DecisionBase(ImmutableModel):
    rule_id: RuleId
    rule_version: Version
    rules_artifact_version: Version
    reason_code: ReasonCode
    reason: Text
    priority: Priority
    tie_order: TieOrder
    trace: tuple[RuleTrace, ...]


class AskDecision(DecisionBase):
    decision: Literal["ask"] = "ask"
    target: SchemaTarget
    concrete_target: Text
    question_id: QuestionId
    proposed_change: None = None


class DeriveDecision(DecisionBase):
    decision: Literal["derive"] = "derive"
    target: Literal[SchemaTarget.CENTER_STONE_DIMENSIONS]
    concrete_target: Literal["center_stone.dimensions"]
    question_id: None = None
    proposed_change: ProposedDerivedChange


class AssumeDecision(DecisionBase):
    decision: Literal["assume"] = "assume"
    target: SchemaTarget
    concrete_target: Text
    question_id: None = None
    proposed_change: ProposedAssumedChange


class BlockDecision(DecisionBase):
    decision: Literal["block"] = "block"
    target: SchemaTarget | None
    concrete_target: Text | None
    question_id: None = None
    proposed_change: None = None
    conflict_rule_ids: tuple[RuleId, ...] = ()


class ReadyDecision(DecisionBase):
    decision: Literal["ready"] = "ready"
    target: None = None
    concrete_target: None = None
    question_id: None = None
    proposed_change: None = None


RuleDecision = Annotated[
    AskDecision | DeriveDecision | AssumeDecision | BlockDecision | ReadyDecision,
    Field(discriminator="decision"),
]


def _state_for_target(revision: DesignRevision, target: SchemaTarget):
    design = revision.design
    if target == SchemaTarget.CENTER_STONE_SHAPE:
        return ((target.value, design.center_stone.shape, None),)
    if target == SchemaTarget.CENTER_STONE_DIMENSIONS:
        return ((target.value, design.center_stone.dimensions, None),)
    if target == SchemaTarget.CENTER_STONE_SETTING:
        return ((target.value, design.center_stone.setting, None),)
    if target == SchemaTarget.METAL_COLOR:
        return ((target.value, design.metal.color, None),)
    return tuple(
        (f"side_stones.{group.group_id}.quantity", group.quantity, group.group_id)
        for group in sorted(design.side_stones, key=lambda item: item.group_id)
    )


def _gap_state(state) -> GapState:
    if state is None:
        return GapState.ABSENT
    if isinstance(state, Unknown):
        return GapState.UNKNOWN
    if isinstance(state, KnownValue):
        return GapState.SATISFIED
    return GapState.UNSATISFIED


def analyze_gaps(
    revision: DesignRevision,
    *,
    questions: QuestionCatalog,
    required_targets: tuple[SchemaTarget, ...] = tuple(SchemaTarget),
) -> tuple[Gap, ...]:
    """Inspect only the five bounded v1 targets; collection groups sort by stable group_id."""
    revision = DesignRevision.model_validate(revision)
    required = set(required_targets)
    gaps: list[Gap] = []
    for target in SchemaTarget:
        question_id = _QUESTION_BY_TARGET[target]
        question = questions.get_question(question_id)
        if question.target != target:
            raise ValueError(f"Question target mismatch for {question_id.value}")
        for concrete_target, state, group_id in _state_for_target(revision, target):
            gaps.append(
                Gap(
                    target=target,
                    concrete_target=concrete_target,
                    state=_gap_state(state),
                    required=target in required,
                    confirmed=bool(getattr(state, "confirmed", False)),
                    locked=bool(getattr(state, "locked", False)),
                    group_id=group_id,
                    question_id=question_id,
                )
            )
    return tuple(gaps)


class RuleRegistry(Mapping[str, Rule]):
    """Validated immutable rules plus the bounded deterministic interpreter."""

    def __init__(
        self,
        bundle: RulesBundle,
        *,
        roles: RoleRegistry,
        dictionary: DictionaryRegistry,
        questions: QuestionCatalog,
    ):
        bundle = RulesBundle.model_validate(bundle)
        expected_versions = (
            ("role", bundle.role_artifact_version, roles.artifact_version),
            ("dictionary", bundle.dictionary_artifact_version, dictionary.artifact_version),
            ("question", bundle.question_artifact_version, questions.artifact_version),
        )
        for name, pinned, supplied in expected_versions:
            if pinned != supplied:
                raise ValueError(f"Rules {name} artifact version does not match the registry")

        for target, question_id in _QUESTION_BY_TARGET.items():
            if questions.get_question(question_id).target != target:
                raise ValueError(f"Question {question_id.value} does not match {target.value}")
        for rule in bundle.rules:
            if isinstance(rule.action, AskAction):
                question = questions.get_question(rule.action.question_id)
                if question.target != rule.target:
                    raise ValueError(f"Rule {rule.rule_id} has a wrong target/question pairing")
            for condition in rule.conditions:
                if isinstance(condition, FieldEqualsCondition):
                    self._validate_dictionary_reference(
                        dictionary,
                        condition.target,
                        condition.value,
                        condition.dictionary_category,
                    )
            if isinstance(rule.action, AssumeAction):
                self._validate_dictionary_reference(
                    dictionary,
                    rule.target,
                    rule.action.value,
                    rule.action.dictionary_category,
                )

        self._bundle = bundle
        self._roles = roles
        self._dictionary = dictionary
        self._questions = questions
        self._entries = MappingProxyType({rule.rule_id: rule for rule in bundle.rules})
        self._dependency_order = _dependency_order(bundle.rules)
        self._evaluation_order = tuple(
            sorted(bundle.rules, key=lambda item: (-item.priority, item.tie_order, item.rule_id))
        )

    @staticmethod
    def _validate_dictionary_reference(dictionary, target, value, declared_category):
        expected = _DICTIONARY_TARGET_CATEGORIES.get(target)
        if expected != declared_category:
            raise ValueError(f"Wrong dictionary category for target {target.value}")
        try:
            entry = dictionary[value]
        except KeyError as exc:
            raise ValueError(f"Unknown dictionary ID: {value}") from exc
        if entry.category != declared_category:
            raise ValueError(f"Dictionary ID {value} has the wrong category")

    @property
    def artifact_version(self) -> str:
        return self._bundle.artifact_version

    @property
    def required_targets(self) -> tuple[SchemaTarget, ...]:
        return self._bundle.required_targets

    def __getitem__(self, rule_id: str) -> Rule:
        return self._entries[rule_id]

    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def _validate_fact(self, fact: AvailableKnowledgeFact) -> None:
        references = (
            (fact.match.jewelry_type, DictionaryCategory.JEWELRY_TYPE),
            (fact.match.center_stone_material, DictionaryCategory.GEMSTONE_MATERIAL),
        )
        for value, category in references:
            try:
                entry = self._dictionary[value]
            except KeyError as exc:
                raise ValueError(f"Unknown knowledge-fact dictionary ID: {value}") from exc
            if entry.category != category:
                raise ValueError(f"Knowledge-fact ID {value} has the wrong category")

    @staticmethod
    def _known_value(state):
        return state.value if isinstance(state, KnownValue) else None

    def _matching_facts(
        self, revision: DesignRevision, facts: tuple[AvailableKnowledgeFact, ...]
    ) -> tuple[AvailableKnowledgeFact, ...]:
        design = revision.design
        jewelry_type = self._known_value(design.jewelry_type)
        material = self._known_value(design.center_stone.material)
        weight = self._known_value(design.center_stone.weight)
        matches = (
            fact
            for fact in facts
            if fact.match.jewelry_type == jewelry_type
            and fact.match.center_stone_material == material
            and fact.match.center_stone_weight == weight
        )
        return tuple(sorted(matches, key=lambda item: (item.source.record_id, item.source.version)))

    def _locked_conflict(
        self, revision: DesignRevision, update: ProposedDomainUpdate | None
    ) -> bool:
        if update is None:
            return False
        self._validate_dictionary_reference(
            self._dictionary,
            update.target,
            update.value,
            DictionaryCategory.METAL_COLOR,
        )
        state = revision.design.metal.color
        return bool(isinstance(state, KnownValue) and state.locked and state.value != update.value)

    def evaluate(
        self,
        revision: DesignRevision,
        role_id: RoleId | str,
        *,
        knowledge_facts: tuple[AvailableKnowledgeFact, ...] = (),
        proposed_update: ProposedDomainUpdate | None = None,
    ) -> RuleDecision:
        revision = DesignRevision.model_validate(revision)
        profile = self._roles.get_profile(role_id)
        facts = tuple(AvailableKnowledgeFact.model_validate(item) for item in knowledge_facts)
        for fact in facts:
            self._validate_fact(fact)
        matching_facts = self._matching_facts(revision, facts)
        gaps = analyze_gaps(
            revision, questions=self._questions, required_targets=self.required_targets
        )
        gaps_by_target = {
            target: tuple(item for item in gaps if item.target == target) for target in SchemaTarget
        }
        locked_conflict = self._locked_conflict(revision, proposed_update)

        condition_traces: dict[str, tuple[ConditionTrace, ...]] = {}
        direct: dict[str, bool] = {}
        for rule in self._bundle.rules:
            traces = tuple(
                self._evaluate_condition(
                    condition,
                    revision=revision,
                    profile=profile,
                    gaps=gaps,
                    gaps_by_target=gaps_by_target,
                    matching_facts=matching_facts,
                    locked_conflict=locked_conflict,
                )
                for condition in rule.conditions
            )
            condition_traces[rule.rule_id] = traces
            direct[rule.rule_id] = all(item.outcome for item in traces)

        applicable: dict[str, bool] = {}
        for rule_id in self._dependency_order:
            rule = self._entries[rule_id]
            applicable[rule_id] = direct[rule_id] and all(
                applicable[dependency] for dependency in rule.depends_on
            )

        candidates = tuple(rule for rule in self._evaluation_order if applicable[rule.rule_id])
        if not candidates:
            trace = self._build_trace(
                condition_traces, applicable, selected=(), gaps_by_target=gaps_by_target
            )
            return BlockDecision(
                rule_id="engine_no_decision",
                rule_version=RULES_SCHEMA_VERSION,
                rules_artifact_version=self.artifact_version,
                reason_code=ReasonCode.NO_VALID_DECISION,
                reason="No validated rule produced a decision for the current state.",
                priority=0,
                tie_order=0,
                target=None,
                concrete_target=None,
                trace=trace,
            )

        top_priority = candidates[0].priority
        top = tuple(rule for rule in candidates if rule.priority == top_priority)
        conflicts = self._runtime_conflicts(top, gaps_by_target)
        if conflicts:
            involved = tuple(sorted(rule.rule_id for rule in conflicts))
            target = conflicts[0].target
            concrete = self._concrete_target(conflicts[0], gaps_by_target)
            trace = self._build_trace(
                condition_traces, applicable, selected=(), gaps_by_target=gaps_by_target
            )
            return BlockDecision(
                rule_id="engine_rule_conflict",
                rule_version=RULES_SCHEMA_VERSION,
                rules_artifact_version=self.artifact_version,
                reason_code=ReasonCode.RULE_CONFLICT,
                reason="Applicable rules propose incompatible actions at the same priority.",
                priority=top_priority,
                tie_order=min(rule.tie_order for rule in conflicts),
                target=target,
                concrete_target=concrete,
                conflict_rule_ids=involved,
                trace=trace,
            )

        selected = candidates[0]
        trace = self._build_trace(
            condition_traces,
            applicable,
            selected=(selected.rule_id,),
            gaps_by_target=gaps_by_target,
        )
        concrete = self._concrete_target(selected, gaps_by_target)
        common = dict(
            rule_id=selected.rule_id,
            rule_version=selected.rule_version,
            rules_artifact_version=self.artifact_version,
            reason_code=selected.reason_code,
            reason=selected.reason,
            priority=selected.priority,
            tie_order=selected.tie_order,
            trace=trace,
        )
        if isinstance(selected.action, (DeriveAction, AssumeAction)) and any(
            bool(getattr(state, "locked", False))
            for _, state, _ in _state_for_target(revision, selected.target)
        ):
            return BlockDecision(
                rule_id=selected.rule_id,
                rule_version=selected.rule_version,
                rules_artifact_version=self.artifact_version,
                reason_code=ReasonCode.LOCKED_FIELD_CONFLICT,
                reason="A rule cannot propose a value for a locked target.",
                priority=selected.priority,
                tie_order=selected.tie_order,
                target=selected.target,
                concrete_target=concrete,
                trace=trace,
            )
        if isinstance(selected.action, AskAction):
            return AskDecision(
                **common,
                target=selected.target,
                concrete_target=concrete,
                question_id=selected.action.question_id,
            )
        if isinstance(selected.action, DeriveAction):
            fact = matching_facts[0]
            state = Derived[Dimensions](
                value=fact.value,
                sources=(fact.source,),
                uncertainty=fact.uncertainty,
                confirmed=False,
                locked=False,
            )
            proposal = ProposedDerivedChange(
                target=SchemaTarget.CENTER_STONE_DIMENSIONS,
                concrete_target="center_stone.dimensions",
                state=state,
            )
            return DeriveDecision(
                **common,
                target=SchemaTarget.CENTER_STONE_DIMENSIONS,
                concrete_target="center_stone.dimensions",
                proposed_change=proposal,
            )
        if isinstance(selected.action, AssumeAction):
            source = RuleSource(
                rule_id=selected.rule_id,
                version=selected.rule_version,
                recorded_at=selected.action.recorded_at,
            )
            state = Assumed[DomainId](
                value=selected.action.value,
                source=source,
                rationale=selected.action.rationale,
                confirmed=False,
                locked=False,
            )
            proposal = ProposedAssumedChange(
                target=selected.target, concrete_target=concrete, state=state
            )
            return AssumeDecision(
                **common,
                target=selected.target,
                concrete_target=concrete,
                proposed_change=proposal,
            )
        if isinstance(selected.action, BlockAction):
            return BlockDecision(
                **common,
                target=selected.target,
                concrete_target=concrete,
            )
        return ReadyDecision(**common)

    def _evaluate_condition(
        self,
        condition,
        *,
        revision,
        profile,
        gaps,
        gaps_by_target,
        matching_facts,
        locked_conflict,
    ) -> ConditionTrace:
        if isinstance(condition, TargetStateCondition):
            matched = tuple(
                gap for gap in gaps_by_target[condition.target] if gap.state in condition.states
            )
            return ConditionTrace(
                condition_kind=condition.kind,
                outcome=bool(matched),
                detail=(
                    f"{len(matched)} concrete target(s) match states "
                    f"{','.join(state.value for state in condition.states)}"
                ),
            )
        if isinstance(condition, RoleCondition):
            outcome = profile.role_id == condition.role_id
            return ConditionTrace(
                condition_kind=condition.kind,
                outcome=outcome,
                detail=f"role={profile.role_id.value}; expected={condition.role_id.value}",
            )
        if isinstance(condition, RoleDerivationCondition):
            actual = profile.derivation_policy.mode
            return ConditionTrace(
                condition_kind=condition.kind,
                outcome=actual == condition.mode,
                detail=f"mode={actual.value}; expected={condition.mode.value}",
            )
        if isinstance(condition, KnowledgeFactCondition):
            outcome = bool(matching_facts) == condition.exists
            return ConditionTrace(
                condition_kind=condition.kind,
                outcome=outcome,
                detail=(
                    f"compatible_facts={len(matching_facts)}; expected_exists={condition.exists}"
                ),
                source_ids=tuple(fact.source.record_id for fact in matching_facts),
            )
        if isinstance(condition, LockedUpdateConflictCondition):
            return ConditionTrace(
                condition_kind=condition.kind,
                outcome=locked_conflict,
                detail=f"locked_conflict={locked_conflict}",
            )
        if isinstance(condition, FieldEqualsCondition):
            values = tuple(
                self._known_value(state)
                for _, state, _ in _state_for_target(revision, condition.target)
            )
            return ConditionTrace(
                condition_kind=condition.kind,
                outcome=condition.value in values,
                detail=f"canonical_value={condition.value}",
            )
        satisfied = all(not gap.required or gap.state == GapState.SATISFIED for gap in gaps)
        return ConditionTrace(
            condition_kind=condition.kind,
            outcome=satisfied,
            detail=f"all_required_targets_satisfied={satisfied}",
        )

    def _concrete_target(self, rule, gaps_by_target) -> str | None:
        if rule.target is None:
            return None
        candidates = gaps_by_target[rule.target]
        for condition in rule.conditions:
            if isinstance(condition, TargetStateCondition):
                matching = tuple(gap for gap in candidates if gap.state in condition.states)
                if matching:
                    return matching[0].concrete_target
        return candidates[0].concrete_target if candidates else rule.target.value

    def _runtime_conflicts(self, rules, gaps_by_target) -> tuple[Rule, ...]:
        for index, left in enumerate(rules):
            left_concrete = self._concrete_target(left, gaps_by_target)
            for right in rules[index + 1 :]:
                if (
                    left_concrete == self._concrete_target(right, gaps_by_target)
                    and left.target == right.target
                    and left.action != right.action
                ):
                    return (left, right)
        return ()

    def _build_trace(
        self,
        condition_traces,
        applicable,
        *,
        selected,
        gaps_by_target=None,
    ) -> tuple[RuleTrace, ...]:
        gaps_by_target = gaps_by_target or {target: () for target in SchemaTarget}
        return tuple(
            RuleTrace(
                rule_id=rule.rule_id,
                priority=rule.priority,
                tie_order=rule.tie_order,
                target=rule.target,
                concrete_target=self._concrete_target(rule, gaps_by_target),
                action_considered=ActionKind(rule.action.kind),
                conditions=condition_traces[rule.rule_id],
                applicable=applicable[rule.rule_id],
                selected=rule.rule_id in selected,
            )
            for rule in self._evaluation_order
        )


def load_rules(
    path: str | Path,
    *,
    roles: RoleRegistry,
    dictionary: DictionaryRegistry,
    questions: QuestionCatalog,
) -> RuleRegistry:
    """Load one explicit rules artifact and validate every pinned cross-reference."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return RuleRegistry(
        RulesBundle.model_validate(data),
        roles=roles,
        dictionary=dictionary,
        questions=questions,
    )
