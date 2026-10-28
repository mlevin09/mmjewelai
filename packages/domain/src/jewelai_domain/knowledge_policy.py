"""Deterministic Knowledge Library runtime state and policy evaluation."""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, StrictBool, model_validator

from .knowledge_library import CompiledKnowledgeLibrary, CompiledPolicy, PolicyTarget
from .knowledge_library_v1_1 import CompiledKnowledgeLibraryV1_1, CompiledPolicyV1_1
from .knowledge_targets_v1_1 import target_family_from_concrete
from .lock_protection import (
    first_locked_change,
    locked_ancestor,
    state_fields,
    validate_replacement_value,
    value_state_fields,
)
from .models import (
    Assumed,
    Derived,
    Explicit,
    ImmutableModel,
    KnownValue,
    NotApplicable,
    Text,
    Unknown,
)
from .models_v1_1 import AnyDesignRevision, validate_design_revision
from .state_paths import iter_knowledge_state_fields

CANONICAL_POLICY_EVALUATION_VERSION = "2.0.0"


def _expanded_target(target):
    # Reuse the frozen grammar, not a second list of legacy scalar/group leaves.
    from .knowledge_library import _ALLOWED_POLICY_TARGETS

    parts = target.split(".")
    if parts[0] in {"composition", "decorative_elements"} or parts[:2] == [
        "metal",
        "components",
    ]:
        return True
    family = target_family_from_concrete(target)
    return family is not None and family not in _ALLOWED_POLICY_TARGETS


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

_ALLOWED_PROPOSAL_PROVENANCE = {
    RuntimeSemanticState.EXPLICIT: frozenset(
        {
            RuntimeProvenance.USER_CONFIRMED,
            RuntimeProvenance.USER_EXPLICIT_LATEST,
        }
    ),
    RuntimeSemanticState.NORMALIZED: frozenset(
        {
            RuntimeProvenance.USER_CONFIRMED,
            RuntimeProvenance.NORMALIZED_FROM_USER,
        }
    ),
    RuntimeSemanticState.AMBIGUOUS: frozenset(
        {
            RuntimeProvenance.NORMALIZED_FROM_USER,
            RuntimeProvenance.KNOWLEDGE_INFERRED,
        }
    ),
    RuntimeSemanticState.RECOMMENDED: frozenset(
        {
            RuntimeProvenance.KNOWLEDGE_INFERRED,
            RuntimeProvenance.JEWELAI_RECOMMENDED,
        }
    ),
    RuntimeSemanticState.ACCEPTED: frozenset({RuntimeProvenance.USER_ACCEPTED_RECOMMENDATION}),
    RuntimeSemanticState.ASSUMED: frozenset(
        {
            RuntimeProvenance.USER_CONFIRMED,
            RuntimeProvenance.VISUALIZATION_ASSUMPTION,
        }
    ),
    RuntimeSemanticState.NOT_APPLICABLE: frozenset({RuntimeProvenance.USER_CONFIRMED}),
}
_KNOWLEDGE_LINEAGE_PROVENANCE = frozenset(
    {
        RuntimeProvenance.KNOWLEDGE_INFERRED,
        RuntimeProvenance.JEWELAI_RECOMMENDED,
        RuntimeProvenance.USER_ACCEPTED_RECOMMENDATION,
    }
)


def validate_proposal_authority(
    semantic_state: RuntimeSemanticState,
    provenance: RuntimeProvenance,
) -> None:
    """Reject proposal state/provenance combinations that misstate their authority."""

    allowed = _ALLOWED_PROPOSAL_PROVENANCE.get(semantic_state, frozenset())
    if provenance not in allowed:
        raise ValueError(
            f"{semantic_state.value} proposal cannot use {provenance.value} provenance"
        )


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
    source_id: Text
    preservation: PreservationIntent = PreservationIntent.CHANGE

    @model_validator(mode="after")
    def validate_proposal(self):
        if self.source_id != self.source_id.strip():
            raise ValueError("runtime proposal source_id must be exact")
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
        validate_proposal_authority(self.semantic_state, self.provenance)
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
    runtime: CompiledKnowledgeLibrary | CompiledKnowledgeLibraryV1_1,
    revision: AnyDesignRevision | object,
) -> KnowledgeRuntimeState:
    """Project one immutable DesignRevision into Knowledge Library runtime state.

    Schema v1.0.0 preserves the historical projection exactly. Schema v1.1.0
    adds the frozen P0-16 Product State targets through the shared version-aware
    traversal; Reference Binding and Visualization Verification remain outside
    this state.
    """
    runtime = _validate_compiled_runtime(runtime)
    revision = validate_design_revision(revision)
    parameters = [
        _from_design_state(target, state) for target, state in iter_knowledge_state_fields(revision)
    ]
    group_ids = tuple(sorted(group.group_id for group in revision.design.side_stones))

    return KnowledgeRuntimeState(
        package_id=runtime.package_id,
        artifact_version=runtime.artifact_version,
        runtime_sha256=runtime.sha256,
        existing_group_ids=group_ids,
        parameters=tuple(sorted(parameters, key=lambda item: item.target)),
    )


def _validate_compiled_runtime(
    runtime: CompiledKnowledgeLibrary | CompiledKnowledgeLibraryV1_1 | object,
) -> CompiledKnowledgeLibrary | CompiledKnowledgeLibraryV1_1:
    contract_version = (
        runtime.get("contract_version")
        if isinstance(runtime, dict)
        else getattr(runtime, "contract_version", None)
    )
    if contract_version == "1.1.0":
        return CompiledKnowledgeLibraryV1_1.model_validate(runtime)
    return CompiledKnowledgeLibrary.model_validate(runtime)


_PLACEHOLDERS = frozenset({"{group_id}", "{component_id}", "{element_id}"})


def _template_bindings(template: str, target: str) -> dict[str, str] | None:
    template_parts = template.split(".")
    target_parts = target.split(".")
    if len(template_parts) != len(target_parts):
        return None
    bindings = {}
    for expected, actual in zip(template_parts, target_parts, strict=True):
        if expected in _PLACEHOLDERS:
            bindings[expected] = actual
        elif expected != actual:
            return None
    return bindings


class KnowledgePolicyEngine:
    """Apply frozen state precedence and expose matching compiled product policies.

    CompiledPolicy.effect remains reviewed descriptive policy text in Contract v1.0.0. This engine
    never executes or parses that prose. Executable behavior is limited to the contract's generic
    preservation, lock, stable-group and provenance-precedence semantics.
    """

    def __init__(
        self,
        runtime: CompiledKnowledgeLibrary | CompiledKnowledgeLibraryV1_1 | object,
    ):
        self.runtime = _validate_compiled_runtime(runtime)
        self._policies = tuple(sorted(self.runtime.policies, key=lambda item: item.policy_id))
        self._runtime_evidence_ids = (
            frozenset(item.source_id for item in self.runtime.sources)
            | frozenset(item.claim_id for item in self.runtime.claims)
            | frozenset(item.concept_id for item in self.runtime.domain_knowledge)
            | frozenset(item.mapping_id for item in self.runtime.language_mappings)
            | frozenset(item.policy_id for item in self.runtime.policies)
            | frozenset(
                source_ref for item in self.runtime.policies for source_ref in item.source_refs
            )
        )
        self._precedence = {
            provenance: rank for rank, provenance in enumerate(PROVENANCE_PRECEDENCE)
        }

    def policies_for(
        self,
        target: str,
        *,
        existing_group_ids: tuple[str, ...] = (),
    ) -> tuple[CompiledPolicy | CompiledPolicyV1_1, ...]:
        matches = []
        groups = frozenset(existing_group_ids)
        for policy in self._policies:
            if policy.target == target:
                matches.append(policy)
                continue
            bindings = _template_bindings(policy.target, target)
            if bindings is None:
                continue
            group_id = bindings.get("{group_id}")
            if group_id is not None and group_id not in groups:
                continue
            matches.append(policy)
        return tuple(matches)

    def evaluate(
        self,
        state: KnowledgeRuntimeState,
        proposal: RuntimeStateProposal,
    ) -> PolicyEvaluation:
        """Frozen flat v1 leaf policy; expanded operations require canonical v2."""
        state = KnowledgeRuntimeState.model_validate(state)
        proposal = RuntimeStateProposal.model_validate(proposal)
        if (
            isinstance(self.runtime, CompiledKnowledgeLibraryV1_1)
            or _expanded_target(proposal.target)
            or any(_expanded_target(item.target) for item in state.parameters)
        ):
            raise ValueError("Expanded policy evaluation requires the canonical v2 interface")
        return self._evaluate(state, proposal)

    def evaluate_canonical(
        self,
        revision: AnyDesignRevision | object,
        proposal: RuntimeStateProposal,
        *,
        expected_revision_id: UUID,
        effective_state: KnowledgeRuntimeState | None = None,
    ) -> PolicyEvaluation:
        """Canonical policy v2; the caller, not this pure function, owns DB currency/CAS.

        Sequential effective state supplies precedence only. LOCK authority always
        comes from the complete original canonical revision, never a flat summary.
        """
        revision = validate_design_revision(revision)
        if revision.revision_id != expected_revision_id:
            raise ValueError("Canonical policy revision identity mismatch")
        proposal = RuntimeStateProposal.model_validate(proposal)
        canonical = build_knowledge_runtime_state(self.runtime, revision)
        state = (
            canonical
            if effective_state is None
            else KnowledgeRuntimeState.model_validate(effective_state)
        )
        if (
            (state.package_id, state.artifact_version, state.runtime_sha256)
            != (canonical.package_id, canonical.artifact_version, canonical.runtime_sha256)
            or state.existing_group_ids != canonical.existing_group_ids
            or tuple(item.target for item in state.parameters)
            != tuple(item.target for item in canonical.parameters)
        ):
            raise ValueError("Effective policy state does not match canonical runtime context")
        if canonical.get(proposal.target) is None:
            return self._evaluate(canonical, proposal)
        fields = state_fields(revision.design)
        target = tuple(proposal.target.split("."))
        protected = locked_ancestor(fields, target) is not None
        old = fields.get(target)
        # For a non-value proposal, every old descendant would be removed. For a
        # value proposal, type-check the complete replacement before any APPLIED.
        if not protected and revision.schema_version == "1.1.0":
            replacement = None
            if proposal.semantic_state not in {
                RuntimeSemanticState.AMBIGUOUS,
                RuntimeSemanticState.NOT_APPLICABLE,
            }:
                replacement = validate_replacement_value(
                    revision.design, target, proposal.value, source=revision.event.source
                )
            before = value_state_fields(old.value, target) if isinstance(old, KnownValue) else {}
            after = value_state_fields(replacement, target)
            protected = first_locked_change(before, after) is not None
        if protected:
            self._validate_source(proposal)
            current = canonical.get(proposal.target)
            return PolicyEvaluation(
                outcome="BLOCKED",
                reason="locked",
                target=proposal.target,
                current=current,
                proposed=proposal,
                result=current,
                applicable_policy_ids=tuple(
                    policy.policy_id
                    for policy in self.policies_for(
                        proposal.target, existing_group_ids=canonical.existing_group_ids
                    )
                ),
            )
        return self._evaluate(state, proposal)

    def _validate_source(self, proposal):
        if (
            proposal.provenance in _KNOWLEDGE_LINEAGE_PROVENANCE
            and proposal.source_id not in self._runtime_evidence_ids
        ):
            raise ValueError("knowledge proposal source_id does not belong to the selected runtime")

    def _evaluate(
        self, state: KnowledgeRuntimeState, proposal: RuntimeStateProposal
    ) -> PolicyEvaluation:
        state = KnowledgeRuntimeState.model_validate(state)
        proposal = RuntimeStateProposal.model_validate(proposal)
        if (
            state.package_id != self.runtime.package_id
            or state.artifact_version != self.runtime.artifact_version
            or state.runtime_sha256 != self.runtime.sha256
        ):
            raise ValueError("runtime state does not match the policy engine runtime")
        self._validate_source(proposal)

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
