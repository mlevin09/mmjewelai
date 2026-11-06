"""Non-authoritative Smart Defaults *candidate* projection.

This module does not persist, mutate, or release a blocked Final Prompt.
No runtime or API integration is authorized by creating this module.
A versioned Owner-approved policy and downstream contract are prerequisites
for any actual activation.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, JsonValue, StringConstraints, model_validator

from .models import ImmutableModel, Unknown
from .models_v1_1 import validate_design_revision
from .preservation import contract_hash

Target = Annotated[str, StringConstraints(pattern=r"^[a-z_]+(?:\.[a-z_]+)+$")]
RuleId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,79}$")]
Version = Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]


class DefaultPolicyRule(ImmutableModel):
    """Curated proposal rule, not a new canonical or user-authored fact."""

    target_path: Target
    when_jewelry_type: RuleId
    proposed_value: JsonValue
    rule_id: RuleId
    rule_version: Version
    rationale: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class DefaultCandidate(ImmutableModel):
    """Derived on each read from the last authoritative revision."""

    schema_version: Literal["candidate/1.0.0"] = "candidate/1.0.0"
    basis_revision_id: str
    basis_revision_hash: str
    target_path: Target
    proposed_value: JsonValue
    source_kind: Literal["rule"] = "rule"
    rule_id: RuleId
    rule_version: Version
    rationale: str
    candidate_hash: str

    @model_validator(mode="after")
    def verify_hash(self):
        if self.candidate_hash != contract_hash(
            "jewelai.SmartDefaultCandidate/candidate-1.0.0",
            self.model_dump(mode="json", exclude={"candidate_hash"}),
        ):
            raise ValueError("default candidate hash mismatch")
        return self


def _path_value(design, target: str):
    current = design
    components = target.split(".")
    for component in components:
        if not hasattr(current, "model_fields") or component not in type(current).model_fields:
            raise ValueError(f"unsupported canonical target path: {target}")
        current = getattr(current, component)
    # A path must terminate at a state leaf, not a whole component.
    if current is not None and not hasattr(current, "availability"):
        raise ValueError(f"target must refer to a canonical state leaf: {target}")
    return current


def select_default_candidates(
    revision,
    rules: tuple[DefaultPolicyRule, ...],
    *,
    blocked_targets: frozenset[str],
) -> tuple[DefaultCandidate, ...]:
    """Pure latest-revision projection; nothing is written to Product State.

    The caller MUST supply active protected/KEEP/pending target paths in
    blocked_targets; this candidate layer is not a protection authority.
    Unknown and absent leaf values may be proposed. Explicit, derived,
    assumed, not-applicable, confirmed and locked states are never overwritten.
    """
    revision = validate_design_revision(revision)
    design = revision.design
    jewelry = design.jewelry_type
    if jewelry is None or getattr(jewelry, "availability", None) != "value":
        return ()
    kind = jewelry.value
    revision_hash = contract_hash(
        "jewelai.SmartDefaultRevisionBasis/candidate-1.0.0",
        revision.model_dump(mode="json"),
    )
    seen: set[str] = set()
    proposals = []
    for rule in sorted(rules, key=lambda item: item.target_path):
        if rule.target_path in seen:
            raise ValueError("duplicate default target")
        seen.add(rule.target_path)
        if rule.when_jewelry_type != kind:
            continue
        # A protected parent or descendant prevents assumption until its
        # active boundaries are independently verified.
        if any(
            rule.target_path == protected
            or rule.target_path.startswith(protected + ".")
            or protected.startswith(rule.target_path + ".")
            for protected in blocked_targets
        ):
            continue
        current = _path_value(design, rule.target_path)
        if current is not None and not isinstance(current, Unknown):
            continue
        payload = dict(
            schema_version="candidate/1.0.0",
            basis_revision_id=str(revision.revision_id),
            basis_revision_hash=revision_hash,
            target_path=rule.target_path,
            proposed_value=rule.proposed_value,
            source_kind="rule",
            rule_id=rule.rule_id,
            rule_version=rule.rule_version,
            rationale=rule.rationale,
        )
        proposals.append(
            DefaultCandidate(
                **payload,
                candidate_hash=contract_hash(
                    "jewelai.SmartDefaultCandidate/candidate-1.0.0", payload
                ),
            )
        )
    return tuple(proposals)
