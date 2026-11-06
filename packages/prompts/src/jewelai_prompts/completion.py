"""Opt-in completion6: explicit NO, versioned policy and an immutable effective overlay."""

import json
from typing import Literal
from uuid import UUID

from jewelai_domain.clarification_state import StrictEvidenceModel, evidence_hash
from jewelai_domain.models_v1_1 import AnyDesignRevision, validate_design_revision
from jewelai_domain.preservation import contract_hash
from jewelai_domain.smart_defaults_candidate import (
    DefaultCandidate,
    DefaultPolicyRule,
    _path_value,
    select_default_candidates,
)
from pydantic import AwareDatetime, Field, JsonValue, model_validator

from .compiler import compile_prompt
from .completion_candidate import _overlay
from .final_prompt import FinalPromptConstraint
from .final_prompt_v5 import CanonicalInternalFinalPromptV5, assemble_internal_final_prompt_v5
from .models import PromptTemplateBundle, SpecificationEntry


class CompletionRule(DefaultPolicyRule):
    requires: dict[str, JsonValue] = Field(default_factory=dict)


class CompletionEligibility(StrictEvidenceModel):
    jewelry_type: str
    target: str
    mode: Literal["default_or_omit", "default_only", "user_required"]
    requires: dict[str, JsonValue] = Field(default_factory=dict)


class CompletionRegistry(StrictEvidenceModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    registry_id: str
    version: str
    review_status: Literal["PROPOSED", "APPROVED"]
    rules: tuple[CompletionRule, ...]
    eligibility: tuple[CompletionEligibility, ...]

    @model_validator(mode="after")
    def unique(self):
        ids = [(r.when_jewelry_type, r.target_path) for r in self.rules]
        targets = [(r.jewelry_type, r.target) for r in self.eligibility]
        if len(set(ids)) != len(ids) or len(set(targets)) != len(targets):
            raise ValueError("Duplicate completion policy binding")
        return self

    @property
    def sha256(self):
        return contract_hash("jewelai.CompletionRegistry/1", self)


def _context_matches(design, requires):
    return all(
        getattr(_path_value(design, path), "availability", None) == "value"
        and getattr(_path_value(design, path), "value", None) == value
        for path, value in requires.items()
    )


def _facts(revision, templates):
    return compile_prompt(revision, templates).specification_entries


def _sources(revision, facts):
    from jewelai_domain.lock_protection import state_fields

    fields = state_fields(revision.design)
    sources = {}
    for fact in facts:
        target = tuple(fact.concrete_target.split("."))
        candidates = [
            (p, s)
            for p, s in fields.items()
            if s is not None
            and getattr(s, "availability", None) in {"value", "not_applicable"}
            and target[: len(p)] == p
        ]
        if not candidates:
            raise ValueError("Completion parameter has no canonical provenance")
        _, state = max(candidates, key=lambda item: len(item[0]))
        sources[fact.concrete_target] = state.model_dump(mode="json", exclude={"value"})
    return sources


def _render(facts, constraints, omitted):
    lines = ["JEWELAI INTERNAL FINAL PROMPT 6.0.0", "CURRENT EFFECTIVE DESIGN"]
    for f in facts:
        value = json.dumps(f.value, ensure_ascii=False, sort_keys=True)
        lines.append(f"{f.concrete_target}: {value} [{f.origin}; {f.applicability}]")
    lines.append("ACTIVE CONSTRAINTS — MUST PRESERVE")
    by_target = {f.concrete_target: f.value for f in facts}
    for constraint in constraints:
        target = constraint.target
        value = constraint.value
        has_value = value is not None
        if not has_value and target in by_target:
            value, has_value = by_target[target], True
        elif not has_value and target.startswith("component."):
            # Existing coalesced KEEP ownership, not a new concept-to-target binding.
            prefix = target.removeprefix("component.") + "."
            owned = {p: v for p, v in by_target.items() if p.startswith(prefix)}
            if owned:
                value, has_value = owned, True
        current = ": " + json.dumps(value, ensure_ascii=False, sort_keys=True) if has_value else ""
        lines.append(f"{constraint.kind} {target}{current} — {constraint.instruction}")
    lines.append("LEFT UNSPECIFIED — DO NOT INVENT")
    lines.extend(omitted)
    return "\n".join(lines)


class InternalFinalPromptV6(StrictEvidenceModel):
    schema_version: Literal["6.0.0"] = "6.0.0"
    completion_id: UUID
    completion_message_id: UUID
    completed_at: AwareDatetime
    base_prompt: CanonicalInternalFinalPromptV5
    canonical_revision: AnyDesignRevision
    registry: CompletionRegistry
    explicit_rule_block: bool
    effective_revision: AnyDesignRevision
    assumptions: tuple[DefaultCandidate, ...]
    effective_parameters: tuple[SpecificationEntry, ...]
    parameter_sources: dict[str, dict[str, JsonValue]]
    policy_sha256: str
    constraints: tuple[FinalPromptConstraint, ...]
    omitted_targets: tuple[str, ...]
    readiness: Literal["READY", "READY_WITH_UNRESOLVED"]
    prompt_text: str = Field(max_length=32000)
    content_hash: str

    @model_validator(mode="after")
    def verify(self):
        if self.content_hash != contract_hash(
            "jewelai.InternalFinalPrompt/6.0.0",
            self.model_dump(mode="json", exclude={"content_hash"}),
        ):
            raise ValueError("Completion6 integrity failure")
        if self.base_prompt.current_frame.revision_sha256 != evidence_hash(self.canonical_revision):
            raise ValueError("Completion6 canonical basis mismatch")
        if self.effective_revision.revision_id != self.canonical_revision.revision_id:
            raise ValueError("Completion6 overlay revision mismatch")
        if (
            self.registry.review_status != "APPROVED"
            or self.explicit_rule_block
            or self.base_prompt.protection_projection.pending_requests
        ):
            raise ValueError("Completion6 unauthorized protection/readiness")
        if self.policy_sha256 != self.registry.sha256:
            raise ValueError("Completion6 policy identity mismatch")
        assumptions, effective, omitted = _project_completion(
            self.canonical_revision, self.base_prompt, self.registry, self.completed_at
        )
        if (
            assumptions != self.assumptions
            or effective != self.effective_revision
            or tuple(sorted(omitted)) != self.omitted_targets
            or self.readiness != ("READY_WITH_UNRESOLVED" if omitted else "READY")
        ):
            raise ValueError("Completion6 authoritative projection mismatch")
        if self.constraints != self.base_prompt.constraints:
            raise ValueError("Completion6 constraints lost")
        if self.prompt_text != _render(
            self.effective_parameters, self.constraints, self.omitted_targets
        ):
            raise ValueError("Completion6 rendering mismatch")
        return self


def build_completion(
    snapshot,
    registry,
    *,
    completion_id,
    message_id,
    completed_at,
    dictionary,
    templates,
    source_facts=None,
    pending_descriptions=(),
):
    """Build only under a source-verified scoped write transaction. No provider calls."""
    from jewelai_domain.rules import BlockDecision

    base = assemble_internal_final_prompt_v5(
        snapshot,
        dictionary=dictionary,
        templates=templates,
        _source_facts=source_facts,
        _pending_descriptions=pending_descriptions,
    ).internal_final_prompt
    revision = snapshot.revision
    if registry.review_status != "APPROVED":
        raise ValueError("Unapproved completion policy")
    if base.protection_projection.pending_requests:
        raise ValueError("pending_keep_consent")
    if isinstance(snapshot.rule_decision, BlockDecision) and (
        snapshot.native_frontier is None or not snapshot.rule_decision.blocking_cause_ids
    ):
        raise ValueError("mandatory_decision_unresolved")
    # Legacy blocked histories require explicit existing compatibility proofs, not NO.
    if base.compatibility_projection and (
        base.compatibility_projection.remaining_blocker_refs or base.readiness.value == "blocked"
    ):
        raise ValueError("mandatory_decision_unresolved")
    proposals, effective, omitted = _project_completion(revision, base, registry, completed_at)
    parameters = _facts(effective, templates)
    payload = dict(
        schema_version="6.0.0",
        completion_id=completion_id,
        completion_message_id=message_id,
        completed_at=completed_at,
        base_prompt=base,
        canonical_revision=revision,
        registry=registry,
        explicit_rule_block=False,
        effective_revision=effective,
        assumptions=proposals,
        effective_parameters=parameters,
        parameter_sources=_sources(effective, parameters),
        policy_sha256=registry.sha256,
        constraints=base.constraints,
        omitted_targets=tuple(sorted(omitted)),
        readiness="READY_WITH_UNRESOLVED" if omitted else "READY",
        prompt_text=_render(parameters, base.constraints, tuple(sorted(omitted))),
    )
    return InternalFinalPromptV6(
        **payload, content_hash=contract_hash("jewelai.InternalFinalPrompt/6.0.0", payload)
    )


def _project_completion(revision, base, registry, completed_at):
    kind = getattr(revision.design.jewelry_type, "value", None)
    protected = {
        t.concrete_target for root in base.protection_projection.roots for t in root.scope_targets
    }
    active = [e for e in base.constraint_evidence if e.status == "active"]
    protected.update(e.canonical_target for e in active if e.canonical_target)
    rules = tuple(
        r
        for r in registry.rules
        if r.when_jewelry_type == kind and _context_matches(revision.design, r.requires)
    )
    if any(e.canonical_target is None for e in active):
        protected.update(r.target_path for r in rules)
    proposals = select_default_candidates(revision, rules, blocked_targets=frozenset(protected))
    effective = _overlay(revision, proposals, completed_at)
    decisions = {
        e.target: e
        for e in registry.eligibility
        if e.jewelry_type == kind and _context_matches(revision.design, e.requires)
    }
    omitted = set()
    filled = {p.target_path for p in proposals}
    for target, decision in decisions.items():
        state = _path_value(revision.design, target)
        missing = state is None or getattr(state, "availability", None) == "unknown"
        if missing and decision.mode == "user_required":
            raise ValueError("mandatory_decision_unresolved")
        if missing and decision.mode == "default_only" and target not in filled:
            raise ValueError("mandatory_decision_unresolved")
    for detail in base.unresolved_details:
        kind = getattr(detail, "kind", "information_gap")
        if kind in {"material_alternative", "material_competing"} or (
            kind == "unbound_request" and detail.blocking
        ):
            raise ValueError("conflicting_evidence")
        if detail.target in filled:
            continue
        if detail.blocking:
            policy = decisions.get(detail.target)
            if (
                not policy
                or policy.mode != "default_or_omit"
                or getattr(detail, "kind", "information_gap") != "information_gap"
            ):
                raise ValueError("mandatory_decision_unresolved")
            state = _path_value(revision.design, detail.target)
            if state is not None and getattr(state, "availability", None) != "unknown":
                raise ValueError("inconsistent_gap")
        # An unaccepted interpretation of an existing value is audit evidence, not a gap.
        # Blocking/conflicting evidence was checked above and cannot be discharged here.
        try:
            state = _path_value(effective.design, detail.target)
        except ValueError:
            state = None
        if getattr(state, "availability", None) not in {"value", "not_applicable"}:
            omitted.add(detail.target)
    return proposals, effective, omitted


def validate_completion(payload, templates: PromptTemplateBundle):
    result = InternalFinalPromptV6.model_validate(payload)
    revision = validate_design_revision(result.canonical_revision)
    proposals, effective, omitted = _project_completion(
        revision, result.base_prompt, result.registry, result.completed_at
    )
    if proposals != result.assumptions or tuple(sorted(omitted)) != result.omitted_targets:
        raise ValueError("Completion6 policy/discharge mismatch")
    if (
        result.base_prompt.compatibility_projection
        and result.base_prompt.readiness.value == "blocked"
    ):
        raise ValueError("Completion6 legacy blocker")
    if result.base_prompt.readiness.value == "blocked" and not any(
        d.blocking for d in result.base_prompt.unresolved_details
    ):
        raise ValueError("Completion6 unattributed blocker")
    if len(result.prompt_text.encode()) > 128000:
        raise ValueError("Completion6 capacity exceeded")
    if result.readiness != ("READY_WITH_UNRESOLVED" if omitted else "READY"):
        raise ValueError("Completion6 readiness mismatch")
    basis = {
        f.concrete_target: (f.applicability, f.value, f.origin, f.confirmed, f.locked)
        for f in _facts(revision, templates)
    }
    source = {
        f.target: (f.applicability, f.value, f.origin, f.confirmed, f.locked)
        for f in result.base_prompt.design_facts
    }
    if basis != source:
        raise ValueError("Completion6 base facts mismatch")
    if (
        _sources(effective, result.effective_parameters) != result.parameter_sources
        or effective != result.effective_revision
        or _facts(effective, templates) != result.effective_parameters
    ):
        raise ValueError("Completion6 effective state mismatch")
    return result
