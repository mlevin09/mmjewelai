"""Deterministic Knowledge Library runtime state and policy evaluation."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, StrictBool, model_validator

from .knowledge_library import CompiledKnowledgeLibrary, CompiledPolicy, PolicyTarget
from .models import (
    Assumed,
    Derived,
    DesignRevision,
    Explicit,
    ImmutableModel,
    NotApplicable,
    Unknown,
)


class RuntimeSemanticState(StrEnum):
    EXPLICIT = "EXPLICIT"
    NORMALIZED = "NORMALIZED"
    MISSING = "MISSING"
    AMBIGUOUS = "AMBIGUOUS"
    RECOMMENDED = "RECOMMENDED"
    ACCEPTED = "ACCEPTED"
    ASSUMED = "ASSUMED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class PreservationIntent(StrEnum):
    CHANGE = "CHANGE"
    KEEP = "KEEP"
    LOCKED = "LOCKED"


class RuntimeProvenance(StrEnum):
    USER_CONFIRMED = "USER_CONFIRMED"
    USER_EXPLICIT_LATEST = "USER_EXPLICIT_LATEST"
    USER_ACCEPTED_RECOMMENDATION = "USER_ACCEPTED_RECOMMENDATION"
    NORMALIZED_FROM_USER = "NORMALIZED_FROM_USER"
    KNOWLEDGE_INFERRED = "KNOWLEDGE_INFERRED"
    JEWELAI_RECOMMENDED = "JEWELAI_RECOMMENDED"
    VISUALIZATION_ASSUMPTION = "VISUALIZATION_ASSUMPTION"


PROVENANCE_PRECEDENCE = tuple(RuntimeProvenance)


class RuntimeParameterState(ImmutableModel):
    target: PolicyTarget
    semantic_state: RuntimeSemanticState
    provenance: RuntimeProvenance | None = None
    value: object | None = None
    confirmed: StrictBool = False
    locked: StrictBool = False
    source_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_state(self):
        if self.locked and not self.confirmed:
            raise ValueError("locked runtime state must also be confirmed")
        if self.semantic_state == RuntimeSemanticState.MISSING:
            if self.value is not None or self.provenance is not None:
                raise ValueError("MISSING runtime state cannot carry value or provenance")
        elif self.provenance is None:
            raise ValueError("non-MISSING runtime state requires provenance")
        if (
            self.semantic_state
            in {
                RuntimeSemanticState.AMBIGUOUS,
                RuntimeSemanticState.NOT_APPLICABLE,
            }
            and self.value is not None
        ):
            raise ValueError(f"{self.semantic_state.value} runtime state cannot carry a value")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("runtime source_ids must be unique")
        return self


class KnowledgeRuntimeState(ImmutableModel):
    package_id: str
    artifact_version: str
    runtime_sha256: str
    existing_group_ids: tuple[str, ...] = ()
    parameters: tuple[RuntimeParameterState, ...] = ()

    @model_validator(mode="after")
    def validate_snapshot(self):
        targets = [item.target for item in self.parameters]
        if len(set(targets)) != len(targets):
            raise ValueError("runtime parameter targets must be unique")
        if targets != sorted(targets):
            raise ValueError("runtime parameters must use stable target order")
        if len(set(self.existing_group_ids)) != len(self.existing_group_ids):
            raise ValueError("existing_group_ids must be unique")
        if self.existing_group_ids != tuple(sorted(self.existing_group_ids)):
            raise ValueError("existing_group_ids must use stable order")
        return self

    def get(self, target: str) -> RuntimeParameterState | None:
        return next((item for item in self.parameters if item.target == target), None)


class RuntimeStateProposal(ImmutableModel):
    target: PolicyTarget
    semantic_state: RuntimeSemanticState
    provenance: RuntimeProvenance
    value: object | None = None
    source_id: str
    preservation: PreservationIntent = PreservationIntent.CHANGE

    @model_validator(mode="after")
    def validate_proposal(self):
        if self.semantic_state == RuntimeSemanticState.MISSING:
            raise ValueError("MISSING is an observed state, not an update proposal")
        if (
            self.semantic_state
            in {
                RuntimeSemanticState.AMBIGUOUS,
                RuntimeSemanticState.NOT_APPLICABLE,
            }
            and self.value is not None
        ):
            raise ValueError(f"{self.semantic_state.value} proposal cannot carry a value")
        return self


class PolicyEvaluation(ImmutableModel):
    outcome: Literal["APPLIED", "KEPT", "BLOCKED"]
    reason: Literal[
        "higher_or_equal_precedence",
        "preserve_keep",
        "lower_precedence",
        "locked",
        "preserve_locked",
        "unknown_collection_group",
        "unknown_target",
    ]
    target: PolicyTarget
    current: RuntimeParameterState
    proposed: RuntimeStateProposal
    result: RuntimeParameterState
    applicable_policy_ids: tuple[str, ...]


def _runtime_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return tuple(_runtime_value(item) for item in value)
    return value


def _from_design_state(target: str, state: object | None) -> RuntimeParameterState:
    if state is None or isinstance(state, Unknown):
        return RuntimeParameterState(
            target=target,
            semantic_state=RuntimeSemanticState.MISSING,
        )
    if isinstance(state, NotApplicable):
        return RuntimeParameterState(
            target=target,
            semantic_state=RuntimeSemanticState.NOT_APPLICABLE,
            provenance=RuntimeProvenance.USER_CONFIRMED,
            confirmed=True,
            locked=state.locked,
            source_ids=(state.source.message_id,),
        )
    if isinstance(state, Explicit):
        provenance = (
            RuntimeProvenance.USER_CONFIRMED
            if state.confirmed
            else RuntimeProvenance.USER_EXPLICIT_LATEST
        )
        return RuntimeParameterState(
            target=target,
            semantic_state=RuntimeSemanticState.EXPLICIT,
            provenance=provenance,
            value=_runtime_value(state.value),
            confirmed=state.confirmed,
            locked=state.locked,
            source_ids=(state.source.message_id,),
        )
    if isinstance(state, Derived):
        return RuntimeParameterState(
            target=target,
            semantic_state=(
                RuntimeSemanticState.ACCEPTED
                if state.confirmed
                else RuntimeSemanticState.RECOMMENDED
            ),
            provenance=(
                RuntimeProvenance.USER_ACCEPTED_RECOMMENDATION
                if state.confirmed
                else RuntimeProvenance.KNOWLEDGE_INFERRED
            ),
            value=_runtime_value(state.value),
            confirmed=state.confirmed,
            locked=state.locked,
            source_ids=tuple(
                source.record_id if hasattr(source, "record_id") else source.rule_id
                for source in state.sources
            ),
        )
    if isinstance(state, Assumed):
        return RuntimeParameterState(
            target=target,
            semantic_state=RuntimeSemanticState.ASSUMED,
            provenance=(
                RuntimeProvenance.USER_CONFIRMED
                if state.confirmed
                else RuntimeProvenance.VISUALIZATION_ASSUMPTION
            ),
            value=_runtime_value(state.value),
            confirmed=state.confirmed,
            locked=state.locked,
            source_ids=(state.source.rule_id,),
        )
    raise TypeError(f"unsupported Design state type: {type(state)!r}")


def build_knowledge_runtime_state(
    runtime: CompiledKnowledgeLibrary,
    revision: DesignRevision,
) -> KnowledgeRuntimeState:
    """Project one immutable DesignRevision into Knowledge Library runtime state."""
    runtime = CompiledKnowledgeLibrary.model_validate(runtime)
    revision = DesignRevision.model_validate(revision)
    design = revision.design

    scalar = {
        "jewelry_type": design.jewelry_type,
        "metal.material": design.metal.material,
        "metal.color": design.metal.color,
        "metal.purity": design.metal.purity,
        "metal.finish": design.metal.finish,
        "center_stone.material": design.center_stone.material,
        "center_stone.shape": design.center_stone.shape,
        "center_stone.cut": design.center_stone.cut,
        "center_stone.weight": design.center_stone.weight,
        "center_stone.dimensions": design.center_stone.dimensions,
        "center_stone.color": design.center_stone.color,
        "center_stone.setting": design.center_stone.setting,
        "center_stone.orientation": design.center_stone.orientation,
        "construction.shank": design.construction.shank,
        "construction.gallery": design.construction.gallery,
        "construction.basket": design.construction.basket,
        "construction.clasp": design.construction.clasp,
        "construction.setting_height": design.construction.setting_height,
        "construction.shank_width": design.construction.shank_width,
        "construction.thickness": design.construction.thickness,
        "style": design.style,
    }
    parameters = [_from_design_state(target, state) for target, state in scalar.items()]

    group_ids = tuple(sorted(group.group_id for group in design.side_stones))
    for group in design.side_stones:
        prefix = f"side_stones.{group.group_id}"
        group_states = {
            f"{prefix}.stones.material": group.stones.material,
            f"{prefix}.stones.shape": group.stones.shape,
            f"{prefix}.stones.cut": group.stones.cut,
            f"{prefix}.stones.weight": group.stones.weight,
            f"{prefix}.stones.dimensions": group.stones.dimensions,
            f"{prefix}.stones.color": group.stones.color,
            f"{prefix}.stones.setting": group.stones.setting,
            f"{prefix}.stones.orientation": group.stones.orientation,
            f"{prefix}.quantity": group.quantity,
        }
        parameters.extend(
            _from_design_state(target, state) for target, state in group_states.items()
        )

    return KnowledgeRuntimeState(
        package_id=runtime.package_id,
        artifact_version=runtime.artifact_version,
        runtime_sha256=runtime.sha256,
        existing_group_ids=group_ids,
        parameters=tuple(sorted(parameters, key=lambda item: item.target)),
    )


def _collection_group(template: str, target: str) -> str | None:
    template_parts = template.split(".")
    target_parts = target.split(".")
    if len(template_parts) != len(target_parts):
        return None
    group_id = None
    for expected, actual in zip(template_parts, target_parts, strict=True):
        if expected == "{group_id}":
            group_id = actual
        elif expected != actual:
            return None
    return group_id


class KnowledgePolicyEngine:
    """Apply frozen state precedence and expose matching compiled product policies.

    CompiledPolicy.effect remains reviewed descriptive policy text in Contract v1.0.0. This engine
    never executes or parses that prose. Executable behavior is limited to the contract's generic
    preservation, lock, stable-group and provenance-precedence semantics.
    """

    def __init__(self, runtime: CompiledKnowledgeLibrary):
        self.runtime = CompiledKnowledgeLibrary.model_validate(runtime)
        self._policies = tuple(sorted(self.runtime.policies, key=lambda item: item.policy_id))
        self._precedence = {
            provenance: rank for rank, provenance in enumerate(PROVENANCE_PRECEDENCE)
        }

    def policies_for(
        self,
        target: str,
        *,
        existing_group_ids: tuple[str, ...] = (),
    ) -> tuple[CompiledPolicy, ...]:
        matches = []
        groups = frozenset(existing_group_ids)
        for policy in self._policies:
            if policy.target == target:
                matches.append(policy)
                continue
            if "{group_id}" not in policy.target:
                continue
            group_id = _collection_group(policy.target, target)
            if group_id is not None and group_id in groups:
                matches.append(policy)
        return tuple(matches)

    def evaluate(
        self,
        state: KnowledgeRuntimeState,
        proposal: RuntimeStateProposal,
    ) -> PolicyEvaluation:
        state = KnowledgeRuntimeState.model_validate(state)
        proposal = RuntimeStateProposal.model_validate(proposal)
        if (
            state.package_id != self.runtime.package_id
            or state.artifact_version != self.runtime.artifact_version
            or state.runtime_sha256 != self.runtime.sha256
        ):
            raise ValueError("runtime state does not match the policy engine runtime")

        current = state.get(proposal.target)
        if current is None:
            current = RuntimeParameterState(
                target=proposal.target,
                semantic_state=RuntimeSemanticState.MISSING,
            )
            return PolicyEvaluation(
                outcome="BLOCKED",
                reason="unknown_target",
                target=proposal.target,
                current=current,
                proposed=proposal,
                result=current,
                applicable_policy_ids=(),
            )

        policies = self.policies_for(
            proposal.target,
            existing_group_ids=state.existing_group_ids,
        )
        policy_ids = tuple(policy.policy_id for policy in policies)

        if proposal.target.startswith("side_stones.") and not policies:
            parts = proposal.target.split(".")
            group_id = parts[1] if len(parts) > 1 else ""
            if group_id not in state.existing_group_ids:
                return PolicyEvaluation(
                    outcome="BLOCKED",
                    reason="unknown_collection_group",
                    target=proposal.target,
                    current=current,
                    proposed=proposal,
                    result=current,
                    applicable_policy_ids=(),
                )

        if current.locked:
            return PolicyEvaluation(
                outcome="BLOCKED",
                reason="locked",
                target=proposal.target,
                current=current,
                proposed=proposal,
                result=current,
                applicable_policy_ids=policy_ids,
            )
        if proposal.preservation == PreservationIntent.LOCKED:
            return PolicyEvaluation(
                outcome="BLOCKED",
                reason="preserve_locked",
                target=proposal.target,
                current=current,
                proposed=proposal,
                result=current,
                applicable_policy_ids=policy_ids,
            )
        if proposal.preservation == PreservationIntent.KEEP:
            return PolicyEvaluation(
                outcome="KEPT",
                reason="preserve_keep",
                target=proposal.target,
                current=current,
                proposed=proposal,
                result=current,
                applicable_policy_ids=policy_ids,
            )

        current_rank = (
            self._precedence[current.provenance]
            if current.provenance is not None
            else len(self._precedence)
        )
        proposed_rank = self._precedence[proposal.provenance]
        if proposed_rank > current_rank:
            return PolicyEvaluation(
                outcome="KEPT",
                reason="lower_precedence",
                target=proposal.target,
                current=current,
                proposed=proposal,
                result=current,
                applicable_policy_ids=policy_ids,
            )

        result = RuntimeParameterState(
            target=proposal.target,
            semantic_state=proposal.semantic_state,
            provenance=proposal.provenance,
            value=proposal.value,
            confirmed=proposal.provenance == RuntimeProvenance.USER_CONFIRMED,
            locked=False,
            source_ids=(proposal.source_id,),
        )
        return PolicyEvaluation(
            outcome="APPLIED",
            reason="higher_or_equal_precedence",
            target=proposal.target,
            current=current,
            proposed=proposal,
            result=result,
            applicable_policy_ids=policy_ids,
        )
