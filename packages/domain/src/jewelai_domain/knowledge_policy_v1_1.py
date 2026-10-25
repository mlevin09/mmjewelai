"""Knowledge policy runtime for Knowledge Library Contract v1.1.0."""

from .knowledge_library_v1_1 import CompiledKnowledgeLibraryV1_1, CompiledPolicyV1_1
from .knowledge_policy import (
    _KNOWLEDGE_LINEAGE_PROVENANCE,
    PROVENANCE_PRECEDENCE,
    KnowledgeRuntimeState,
    PolicyEvaluation,
    PreservationIntent,
    RuntimeParameterState,
    RuntimeProvenance,
    RuntimeSemanticState,
    RuntimeStateProposal,
    _from_design_state,
)
from .knowledge_targets_v1_1 import POLICY_TARGET_TEMPLATES_V1_1
from .models_v1_1 import AnyDesignRevision, validate_design_revision
from .state_paths import iter_knowledge_state_fields


def build_knowledge_runtime_state_v1_1(
    runtime: CompiledKnowledgeLibraryV1_1 | object,
    revision: AnyDesignRevision | object,
) -> KnowledgeRuntimeState:
    runtime = CompiledKnowledgeLibraryV1_1.model_validate(runtime)
    revision = validate_design_revision(revision)
    parameters = {
        target: _from_design_state(target, state)
        for target, state in iter_knowledge_state_fields(revision)
    }
    for target in POLICY_TARGET_TEMPLATES_V1_1:
        if "{" not in target and target not in parameters:
            parameters[target] = RuntimeParameterState(
                target=target,
                semantic_state=RuntimeSemanticState.MISSING,
            )
    group_ids = tuple(sorted(group.group_id for group in revision.design.side_stones))
    return KnowledgeRuntimeState(
        package_id=runtime.package_id,
        artifact_version=str(runtime.artifact_version),
        runtime_sha256=runtime.sha256,
        existing_group_ids=group_ids,
        parameters=tuple(sorted(parameters.values(), key=lambda item: item.target)),
    )


def _template_matches(template: str, target: str) -> bool:
    expected_parts = template.split(".")
    actual_parts = target.split(".")
    if len(expected_parts) != len(actual_parts):
        return False
    for expected, actual in zip(expected_parts, actual_parts, strict=True):
        if expected in {"{group_id}", "{component_id}", "{element_id}"}:
            if not actual:
                return False
        elif expected != actual:
            return False
    return True


class KnowledgePolicyEngineV1_1:
    """Apply generic precedence/preservation semantics to v1.1 policy targets."""

    def __init__(self, runtime: CompiledKnowledgeLibraryV1_1 | object):
        self.runtime = CompiledKnowledgeLibraryV1_1.model_validate(runtime)
        self._policies = tuple(
            sorted(self.runtime.policies, key=lambda item: item.policy_id)
        )
        self._runtime_evidence_ids = (
            frozenset(item.source_id for item in self.runtime.sources)
            | frozenset(item.claim_id for item in self.runtime.claims)
            | frozenset(item.concept_id for item in self.runtime.domain_knowledge)
            | frozenset(item.mapping_id for item in self.runtime.language_mappings)
            | frozenset(item.policy_id for item in self.runtime.policies)
            | frozenset(
                source_ref
                for item in self.runtime.policies
                for source_ref in item.source_refs
            )
        )
        self._precedence = {
            provenance: rank
            for rank, provenance in enumerate(PROVENANCE_PRECEDENCE)
        }

    def policies_for(
        self,
        target: str,
        *,
        existing_group_ids: tuple[str, ...] = (),
    ) -> tuple[CompiledPolicyV1_1, ...]:
        del existing_group_ids
        return tuple(
            policy
            for policy in self._policies
            if policy.target == target or _template_matches(policy.target, target)
        )

    def evaluate(
        self,
        state: KnowledgeRuntimeState,
        proposal: RuntimeStateProposal,
    ) -> PolicyEvaluation:
        state = KnowledgeRuntimeState.model_validate(state)
        proposal = RuntimeStateProposal.model_validate(proposal)
        if (
            state.package_id != self.runtime.package_id
            or state.artifact_version != str(self.runtime.artifact_version)
            or state.runtime_sha256 != self.runtime.sha256
        ):
            raise ValueError("runtime state does not match the v1.1 policy engine runtime")
        if (
            proposal.provenance in _KNOWLEDGE_LINEAGE_PROVENANCE
            and proposal.source_id not in self._runtime_evidence_ids
        ):
            raise ValueError(
                "knowledge proposal source_id does not belong to selected v1.1 runtime"
            )

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

        policies = self.policies_for(proposal.target)
        policy_ids = tuple(policy.policy_id for policy in policies)

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
