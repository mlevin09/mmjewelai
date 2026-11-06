"""Unregistered completion contract proposal. No persistence or readiness override.

The overlay is a review artifact, NOT a canonical revision or Internal Final Prompt.
A live caller must supply a source-verified scoped snapshot inside its transaction.
"""

import json
from typing import Literal
from uuid import UUID

from jewelai_domain.clarification_state import EvidenceScope, Sha256, StrictEvidenceModel
from jewelai_domain.continuation import ContinuationFrame
from jewelai_domain.models import Assumed, RuleSource
from jewelai_domain.models_v1_1 import AnyDesignRevision, validate_design_revision
from jewelai_domain.preservation import contract_hash
from jewelai_domain.smart_defaults_candidate import (
    DefaultCandidate,
    DefaultPolicyRule,
    RuleId,
    Version,
    select_default_candidates,
)
from pydantic import AwareDatetime, model_validator

from .compiler import compile_prompt
from .final_prompt import FinalPromptReadiness, _validate_snapshot
from .final_prompt_v4 import (
    CanonicalInternalFinalPromptV4,
    FinalPromptSnapshotV3,
    assemble_internal_final_prompt_v4,
)
from .final_prompt_v5 import CanonicalInternalFinalPromptV5, assemble_internal_final_prompt_v5
from .models import CompiledPrompt


class CompletionIntentCandidate(StrictEvidenceModel):
    schema_version: Literal["completion-intent-candidate/1.0.0"]
    request_id: UUID
    message_id: UUID
    scope: EvidenceScope
    expected_frame: ContinuationFrame
    anything_else: Literal["YES", "NO"]
    recorded_at: AwareDatetime
    content_hash: Sha256

    @model_validator(mode="after")
    def verify(self):
        if self.content_hash != contract_hash(
            "jewelai.CompletionIntentCandidate/1.0.0",
            self.model_dump(mode="json", exclude={"content_hash"}),
        ):
            raise ValueError("Completion intent integrity mismatch")
        return self


class CompletionPolicyCandidate(StrictEvidenceModel):
    schema_version: Literal["completion-policy-candidate/1.0.0"]
    policy_id: RuleId
    policy_version: Version
    rules: tuple[DefaultPolicyRule, ...]


class CompletionReviewCandidate(StrictEvidenceModel):
    schema_version: Literal["completion-review-candidate/1.0.0"]
    status: Literal[
        "EDITING", "FINAL_AVAILABLE", "PROTECTION_BLOCKED", "CONTRACT_APPROVAL_REQUIRED"
    ]
    intent: CompletionIntentCandidate
    policy_sha256: Sha256
    defaults: tuple[DefaultCandidate, ...]
    review_compilation: CompiledPrompt | None
    final_prompt: CanonicalInternalFinalPromptV5 | CanonicalInternalFinalPromptV4 | None
    remaining_blocker_targets: tuple[str, ...]
    content_hash: Sha256

    @model_validator(mode="after")
    def verify(self):
        if self.content_hash != contract_hash(
            "jewelai.CompletionReviewCandidate/1.0.0",
            self.model_dump(mode="json", exclude={"content_hash"}),
        ):
            raise ValueError("Completion review integrity mismatch")
        if (self.final_prompt is not None) != (self.status == "FINAL_AVAILABLE"):
            raise ValueError("Completion result does not authorize a final artifact")
        if self.final_prompt is not None and (
            self.defaults
            or self.intent.anything_else != "NO"
            or self.final_prompt.current_frame != self.intent.expected_frame
            or self.final_prompt.readiness == FinalPromptReadiness.BLOCKED
        ):
            raise ValueError("Completion candidate bypasses readiness or frame")
        return self


def prepare_completion_candidate(
    snapshot,
    intent,
    policy,
    *,
    dictionary,
    templates,
    output_version="4.0.0",
    _source_facts=None,
    _pending_descriptions=(),
) -> CompletionReviewCandidate:
    """Pure, deterministic full-frame check -> typed overlay -> honest finalization gate.

    No policy is approved by calling this function. No API imports/registers it.
    NO is not a discharge for conflicts, pending consent or native obligations.
    Replaying the same validated inputs is deterministic, not durable deduplication.
    """
    snapshot = FinalPromptSnapshotV3.model_validate_json(
        json.dumps(
            snapshot.model_dump(mode="json") if hasattr(snapshot, "model_dump") else snapshot
        )
    )
    intent = CompletionIntentCandidate.model_validate_json(
        json.dumps(intent.model_dump(mode="json") if hasattr(intent, "model_dump") else intent)
    )
    policy = CompletionPolicyCandidate.model_validate_json(
        json.dumps(policy.model_dump(mode="json") if hasattr(policy, "model_dump") else policy)
    )
    if intent.scope != snapshot.protection_projection.scope:
        raise ValueError("Completion scope mismatch")
    if intent.expected_frame != snapshot.current_frame:
        raise ValueError("Stale completion frame")
    builders = {
        "4.0.0": assemble_internal_final_prompt_v4,
        "5.0.0": assemble_internal_final_prompt_v5,
    }
    if output_version not in builders:
        raise ValueError("Unsupported completion output family")
    # Existing builder verifies Matrix, rules, release pins, constraints and source binding.
    pending = bool(snapshot.protection_projection.pending_requests)
    if pending:
        _validate_snapshot(snapshot, dictionary=dictionary, templates=templates)
    current = (
        None
        if pending
        else builders[output_version](
            snapshot,
            dictionary=dictionary,
            templates=templates,
            _source_facts=_source_facts,
            _pending_descriptions=_pending_descriptions,
        )
    )
    source = current.internal_final_prompt if current else None
    defaults, compilation, final = (), None, None
    blocked = (
        tuple(sorted({d.target for d in source.unresolved_details if d.blocking})) if source else ()
    )
    if intent.anything_else == "YES":
        status = "EDITING"
    elif snapshot.protection_projection.pending_requests:
        status = "PROTECTION_BLOCKED"
    else:
        protected = frozenset(
            t.concrete_target
            for root in snapshot.protection_projection.roots
            for t in root.scope_targets
        )
        # Unbound accepted constraints cannot be interpreted as policy bindings.
        # Conservatively withhold assumptions instead of contradicting user evidence.
        active = [e for e in snapshot.constraint_evidence if e.status == "active"]
        protected |= frozenset(e.canonical_target for e in active if e.canonical_target)
        if any(e.canonical_target is None for e in active):
            protected |= frozenset(r.target_path for r in policy.rules)
        defaults = select_default_candidates(
            snapshot.revision, policy.rules, blocked_targets=protected
        )
        effective = _overlay(snapshot.revision, defaults, intent.recorded_at)
        compilation = compile_prompt(effective, templates) if defaults else None
        if defaults or source.readiness == FinalPromptReadiness.BLOCKED:
            # The existing IFP4/5 does NOT describe this overlay. Never relabel it READY.
            status = "CONTRACT_APPROVAL_REQUIRED"
        else:
            status, final = "FINAL_AVAILABLE", source
    payload = dict(
        schema_version="completion-review-candidate/1.0.0",
        status=status,
        intent=intent,
        policy_sha256=contract_hash("jewelai.CompletionPolicyCandidate/1.0.0", policy),
        defaults=defaults,
        review_compilation=compilation,
        final_prompt=final,
        remaining_blocker_targets=blocked,
    )
    return CompletionReviewCandidate(
        **payload, content_hash=contract_hash("jewelai.CompletionReviewCandidate/1.0.0", payload)
    )


def _overlay(revision: AnyDesignRevision, defaults, recorded_at):
    # Full retained-schema revalidation checks the proposed leaf type/value. No groups created.
    wire = revision.model_dump(mode="json")
    for proposal in defaults:
        parent = wire["design"]
        parts = proposal.target_path.split(".")
        for component in parts[:-1]:
            parent = parent[component]
        assumed = Assumed(
            value=proposal.proposed_value,
            source=RuleSource(
                rule_id=proposal.rule_id, version=proposal.rule_version, recorded_at=recorded_at
            ),
            rationale=proposal.rationale,
        )
        parent[parts[-1]] = assumed.model_dump(mode="json")
    return validate_design_revision(wire)
