"""F04 bounded Rules2 extension using the existing Rules interpreter and five-target gaps."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .clarification_state import CauseDefinition, FrontierCore, evidence_hash
from .models import ImmutableModel
from .models_v1_1 import validate_design_revision
from .questions_v2 import QuestionIdV2, SchemaTargetV2
from .rules import (
    AskAction,
    AskDecision,
    AssumeDecision,
    BlockDecision,
    ConditionTrace,
    DeriveDecision,
    ReadyDecision,
    Rule,
    RuleAction,
    RuleCondition,
    RuleProvenance,
    RuleRegistry,
    RulesBundle,
    RuleTrace,
)


class ActiveScopedConflictCondition(ImmutableModel):
    kind: Literal["active_scoped_conflict"]


class AskActionV2(AskAction):
    question_id: QuestionIdV2


class RuleProvenanceV2(RuleProvenance):
    source_ref: Literal[
        "docs/product/issues/05-rules.md",
        "docs/adr/0036-f04-versioned-clarification-profile.md",
    ]


class RuleV2(Rule):
    target: SchemaTargetV2 | None
    conditions: tuple[
        Annotated[RuleCondition | ActiveScopedConflictCondition, Field(discriminator="kind")], ...
    ] = Field(min_length=1)
    action: AskActionV2 | RuleAction
    provenance: RuleProvenanceV2


class RulesBundleV2(RulesBundle):
    schema_version: Literal["2.0.0"]
    artifact_version: Literal["2.0.0"]
    question_artifact_version: Literal["2.0.0"]
    rules: tuple[RuleV2, ...] = Field(min_length=10, max_length=10)

    @model_validator(mode="after")
    def validate_material_rule(self):
        material = [r for r in self.rules if r.rule_id == "ask_unresolved_product_body_material"]
        if len(material) != 1:
            raise ValueError("Rules2 requires its exact bounded material rule")
        rule = material[0]
        if (
            rule.rule_version != "1.0.0"
            or (rule.priority, rule.tie_order) != (950, 15)
            or rule.target != SchemaTargetV2.METAL_MATERIAL
            or not isinstance(rule.action, AskActionV2)
            or rule.action.question_id != QuestionIdV2.METAL_MATERIAL
            or rule.conditions != (ActiveScopedConflictCondition(kind="active_scoped_conflict"),)
            or rule.depends_on
            or rule.provenance.source_ref != "docs/adr/0036-f04-versioned-clarification-profile.md"
        ):
            raise ValueError("Rules2 material rule differs from the approved bounded condition")
        if any(
            isinstance(c, ActiveScopedConflictCondition)
            for r in self.rules
            if r is not rule
            for c in r.conditions
        ):
            raise ValueError("Scoped material conditions cannot change another rule")
        return self


class RuleTraceV2(RuleTrace):
    target: SchemaTargetV2 | None


class RuleContextV2(ImmutableModel):
    frontier_core: FrontierCore
    cause_definitions: tuple[CauseDefinition, ...]

    @model_validator(mode="after")
    def validate_definitions(self):
        by_id = {c.cause_id: c for c in self.cause_definitions}
        if len(by_id) != len(self.cause_definitions) or set(by_id) != {
            c.cause_id for c in self.frontier_core.cause_states
        }:
            raise ValueError("Rule context requires exact scoped cause definitions")
        if any(c.scope != self.frontier_core.scope for c in self.cause_definitions):
            raise ValueError("Rule context cause scope mismatch")
        return self

    @property
    def material_conflict_open(self):
        by_id = {c.cause_id: c for c in self.cause_definitions}
        return any(
            c.blocks_current
            and by_id[c.cause_id].kind in {"material_alternative", "material_competing"}
            and c.offer_state not in {"PROTECTED", "UNREPRESENTABLE"}
            for c in self.frontier_core.cause_states
        )


class EvaluationFieldsV2(ImmutableModel):
    evaluation_version: Literal["2.0.0"] = "2.0.0"
    blocking_cause_ids: tuple[str, ...] = ()
    eligible_clarification_cause_ids: tuple[str, ...] = ()


class AskDecisionV2(AskDecision, EvaluationFieldsV2):
    target: SchemaTargetV2
    question_id: QuestionIdV2
    trace: tuple[RuleTraceV2, ...]


class BlockDecisionV2(BlockDecision, EvaluationFieldsV2):
    target: SchemaTargetV2 | None
    trace: tuple[RuleTraceV2, ...]


class DeriveDecisionV2(DeriveDecision, EvaluationFieldsV2):
    trace: tuple[RuleTraceV2, ...]


class AssumeDecisionV2(AssumeDecision, EvaluationFieldsV2):
    trace: tuple[RuleTraceV2, ...]


class ReadyDecisionV2(ReadyDecision, EvaluationFieldsV2):
    trace: tuple[RuleTraceV2, ...]


class RuleRegistryV2(RuleRegistry):
    _bundle_type = RulesBundleV2
    _trace_type = RuleTraceV2
    _ask_type = AskDecisionV2
    _block_type = BlockDecisionV2
    _derive_type = DeriveDecisionV2
    _assume_type = AssumeDecisionV2
    _ready_type = ReadyDecisionV2

    def evaluate(
        self,
        revision,
        role_id,
        *,
        knowledge_facts=(),
        proposed_update=None,
        unresolved_context=None,
    ):
        revision = validate_design_revision(revision)
        if unresolved_context is not None:
            unresolved_context = RuleContextV2.model_validate(unresolved_context)
            core = unresolved_context.frontier_core
            if (
                core.current_revision_id != revision.revision_id
                or core.revision_sha256 != evidence_hash(revision)
            ):
                raise ValueError("Rules2 context does not match the actual canonical revision")
        decision = super().evaluate(
            revision,
            role_id,
            knowledge_facts=knowledge_facts,
            proposed_update=proposed_update,
            unresolved_context=unresolved_context,
        )
        if unresolved_context is None:
            return decision
        states = unresolved_context.frontier_core.cause_states
        payload = decision.model_dump(mode="json")
        payload["blocking_cause_ids"] = sorted(c.cause_id for c in states if c.blocks_current)
        payload["eligible_clarification_cause_ids"] = sorted(
            c.cause_id for c in states if c.status == "OPEN" and c.offer_state == "AVAILABLE"
        )
        return type(decision).model_validate(payload)

    def _evaluate_condition(self, condition, *, unresolved_context=None, **kwargs):
        if isinstance(condition, ActiveScopedConflictCondition):
            # The runtime supplies verified current evidence, never caller-provided facts.
            eligible = bool(unresolved_context and unresolved_context.material_conflict_open)
            return ConditionTrace(
                condition_kind="active_scoped_conflict",
                outcome=eligible,
                detail="Validated current product-body material conflict"
                if eligible
                else "No eligible current product-body material conflict",
            )
        return super()._evaluate_condition(
            condition, unresolved_context=unresolved_context, **kwargs
        )


RuleDecisionV2 = Annotated[
    AskDecisionV2 | BlockDecisionV2 | DeriveDecisionV2 | AssumeDecisionV2 | ReadyDecisionV2,
    Field(discriminator="decision"),
]
