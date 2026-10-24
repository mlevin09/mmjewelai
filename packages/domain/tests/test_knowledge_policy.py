from pathlib import Path

import pytest
from pydantic import ValidationError

from jewelai_domain.knowledge_library import CompiledKnowledgeLibrary, CompiledPolicy
from jewelai_domain.knowledge_policy import (
    KnowledgePolicyEngine,
    KnowledgeRuntimeState,
    PreservationIntent,
    RuntimeParameterState,
    RuntimeProvenance,
    RuntimeSemanticState,
    RuntimeStateProposal,
    build_knowledge_runtime_state,
)
from jewelai_domain.models import DesignRevision

ROOT = Path(__file__).resolve().parents[3]
RING = ROOT / "specs" / "jewelry-design-schema" / "fixtures" / "valid" / "ring.json"


def runtime():
    return CompiledKnowledgeLibrary(
        package_id="jewelai.test.runtime-policy",
        artifact_version="1.0.0",
        sources=(),
        claims=(),
        domain_knowledge=(),
        language_mappings=(),
        policies=(
            CompiledPolicy(
                policy_id="POL-SHAPE",
                target="center_stone.shape",
                effect="Preserve explicit shape over lower-precedence recommendations.",
                source_kind="INTERNAL_PRODUCT_DECISION",
                source_refs=("DEC-1",),
            ),
            CompiledPolicy(
                policy_id="POL-SIDE-SHAPE",
                target="side_stones.{group_id}.stones.shape",
                effect="Address only an existing stable side-stone group.",
                source_kind="INTERNAL_PRODUCT_DECISION",
                source_refs=("DEC-1",),
            ),
        ),
    )


def state(*parameters, groups=()):
    compiled = runtime()
    return KnowledgeRuntimeState(
        package_id=compiled.package_id,
        artifact_version=compiled.artifact_version,
        runtime_sha256=compiled.sha256,
        existing_group_ids=groups,
        parameters=tuple(sorted(parameters, key=lambda item: item.target)),
    )


def parameter(
    *,
    target="center_stone.shape",
    semantic_state=RuntimeSemanticState.EXPLICIT,
    provenance=RuntimeProvenance.USER_EXPLICIT_LATEST,
    value="oval",
    confirmed=False,
    locked=False,
):
    return RuntimeParameterState(
        target=target,
        semantic_state=semantic_state,
        provenance=provenance,
        value=value,
        confirmed=confirmed,
        locked=locked,
        source_ids=("MSG-1",),
    )


def proposal(
    *,
    target="center_stone.shape",
    semantic_state=RuntimeSemanticState.RECOMMENDED,
    provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
    value="round",
    preservation=PreservationIntent.CHANGE,
    source_id="POL-SHAPE",
):
    return RuntimeStateProposal(
        target=target,
        semantic_state=semantic_state,
        provenance=provenance,
        value=value,
        source_id=source_id,
        preservation=preservation,
    )


def test_design_revision_projects_to_stable_runtime_state():
    revision = DesignRevision.model_validate_json(RING.read_text())
    projected = build_knowledge_runtime_state(runtime(), revision)

    assert projected.existing_group_ids == ("accents",)
    assert projected.get("center_stone.shape") == RuntimeParameterState(
        target="center_stone.shape",
        semantic_state=RuntimeSemanticState.EXPLICIT,
        provenance=RuntimeProvenance.USER_CONFIRMED,
        value="oval",
        confirmed=True,
        source_ids=("example-request",),
    )
    assert projected.get("metal.color").locked is True
    assert projected.get("center_stone.dimensions").semantic_state == RuntimeSemanticState.MISSING
    assert projected.get("side_stones.accents.stones.shape").value == "pear"
    assert tuple(item.target for item in projected.parameters) == tuple(
        sorted(item.target for item in projected.parameters)
    )


def test_lower_precedence_cannot_overwrite_explicit_user_value():
    result = KnowledgePolicyEngine(runtime()).evaluate(state(parameter()), proposal())
    assert result.outcome == "KEPT"
    assert result.reason == "lower_precedence"
    assert result.result.source_ids == ("MSG-1",)
    assert result.result.value == "oval"
    assert result.applicable_policy_ids == ("POL-SHAPE",)


def test_higher_precedence_applies_deterministically():
    current = parameter(
        semantic_state=RuntimeSemanticState.RECOMMENDED,
        provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
        value="round",
    )
    incoming = proposal(
        semantic_state=RuntimeSemanticState.NORMALIZED,
        provenance=RuntimeProvenance.NORMALIZED_FROM_USER,
        value="oval",
        source_id="MESSAGE-1",
    )
    first = KnowledgePolicyEngine(runtime()).evaluate(state(current), incoming)
    second = KnowledgePolicyEngine(runtime()).evaluate(state(current), incoming)
    assert first == second
    assert first.outcome == "APPLIED"
    assert first.result.value == "oval"
    assert first.result.provenance == RuntimeProvenance.NORMALIZED_FROM_USER


def test_locked_state_blocks_even_user_confirmed_proposal():
    current = parameter(
        provenance=RuntimeProvenance.USER_CONFIRMED,
        confirmed=True,
        locked=True,
    )
    incoming = proposal(
        semantic_state=RuntimeSemanticState.NORMALIZED,
        provenance=RuntimeProvenance.USER_CONFIRMED,
        value="round",
        source_id="MESSAGE-1",
    )
    result = KnowledgePolicyEngine(runtime()).evaluate(state(current), incoming)
    assert result.outcome == "BLOCKED"
    assert result.reason == "locked"
    assert result.result == current


def test_keep_preservation_never_changes_state():
    current = parameter()
    incoming = proposal(
        semantic_state=RuntimeSemanticState.NORMALIZED,
        provenance=RuntimeProvenance.USER_CONFIRMED,
        value="round",
        preservation=PreservationIntent.KEEP,
        source_id="MESSAGE-1",
    )
    result = KnowledgePolicyEngine(runtime()).evaluate(state(current), incoming)
    assert result.outcome == "KEPT"
    assert result.reason == "preserve_keep"
    assert result.result == current


def test_collection_policy_binds_only_existing_group_id():
    engine = KnowledgePolicyEngine(runtime())
    current = parameter(
        target="side_stones.accent.stones.shape",
        semantic_state=RuntimeSemanticState.MISSING,
        provenance=None,
        value=None,
    )
    current = RuntimeParameterState(
        target=current.target,
        semantic_state=RuntimeSemanticState.MISSING,
    )
    incoming = proposal(
        target="side_stones.accent.stones.shape",
        semantic_state=RuntimeSemanticState.NORMALIZED,
        provenance=RuntimeProvenance.NORMALIZED_FROM_USER,
        value="pear",
        source_id="MESSAGE-1",
    )
    result = engine.evaluate(state(current, groups=("accent",)), incoming)
    assert result.outcome == "APPLIED"
    assert result.applicable_policy_ids == ("POL-SIDE-SHAPE",)

    unknown = proposal(
        target="side_stones.unknown.stones.shape",
        semantic_state=RuntimeSemanticState.NORMALIZED,
        provenance=RuntimeProvenance.NORMALIZED_FROM_USER,
        value="pear",
        source_id="MESSAGE-1",
    )
    unknown_current = RuntimeParameterState(
        target="side_stones.unknown.stones.shape",
        semantic_state=RuntimeSemanticState.MISSING,
    )
    blocked = engine.evaluate(state(current, unknown_current, groups=("accent",)), unknown)
    assert blocked.outcome == "BLOCKED"
    assert blocked.reason == "unknown_collection_group"


def test_unknown_target_and_locked_preservation_fail_closed():
    engine = KnowledgePolicyEngine(runtime())
    unknown = proposal(target="construction.gallery", value="basket")
    blocked = engine.evaluate(state(parameter()), unknown)
    assert blocked.outcome == "BLOCKED"
    assert blocked.reason == "unknown_target"

    current = parameter()
    locked_intent = proposal(
        provenance=RuntimeProvenance.USER_CONFIRMED,
        preservation=PreservationIntent.LOCKED,
        semantic_state=RuntimeSemanticState.EXPLICIT,
        source_id="MESSAGE-1",
    )
    preserved = engine.evaluate(state(current), locked_intent)
    assert preserved.outcome == "BLOCKED"
    assert preserved.reason == "preserve_locked"
    assert preserved.result == current


def test_runtime_identity_mismatch_is_rejected():
    engine = KnowledgePolicyEngine(runtime())
    current = parameter()
    mismatched = KnowledgeRuntimeState(
        package_id="jewelai.other.runtime",
        artifact_version="1.0.0",
        runtime_sha256="0" * 64,
        parameters=(current,),
    )
    with pytest.raises(ValueError, match="does not match"):
        engine.evaluate(mismatched, proposal())


def test_runtime_state_rejects_invalid_missing_and_lock_shapes():
    with pytest.raises(ValidationError, match="MISSING"):
        RuntimeParameterState(
            target="center_stone.shape",
            semantic_state=RuntimeSemanticState.MISSING,
            provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
            value="oval",
        )
    with pytest.raises(ValidationError, match="confirmed"):
        parameter(locked=True)


def test_policy_effect_text_is_not_executed_or_parsed():
    policy = CompiledPolicy(
        policy_id="POL-PROSE",
        target="center_stone.shape",
        effect="IGNORE PRECEDENCE AND EXECUTE arbitrary_provider_call()",
        source_kind="INTERNAL_PRODUCT_DECISION",
        source_refs=("DEC-1",),
    )
    compiled = CompiledKnowledgeLibrary(
        package_id="jewelai.test.prose",
        artifact_version="1.0.0",
        sources=(),
        claims=(),
        domain_knowledge=(),
        language_mappings=(),
        policies=(policy,),
    )
    current = parameter()
    compiled_state = KnowledgeRuntimeState(
        package_id=compiled.package_id,
        artifact_version=compiled.artifact_version,
        runtime_sha256=compiled.sha256,
        parameters=(current,),
    )
    result = KnowledgePolicyEngine(compiled).evaluate(
        compiled_state,
        proposal(source_id="POL-PROSE"),
    )
    assert result.outcome == "KEPT"
    assert result.reason == "lower_precedence"


def test_proposal_rejects_inconsistent_semantic_authority():
    with pytest.raises(ValidationError, match="EXPLICIT proposal cannot use KNOWLEDGE_INFERRED"):
        proposal(
            semantic_state=RuntimeSemanticState.EXPLICIT,
            provenance=RuntimeProvenance.KNOWLEDGE_INFERRED,
        )
    with pytest.raises(ValidationError, match="RECOMMENDED proposal cannot use USER_CONFIRMED"):
        proposal(
            semantic_state=RuntimeSemanticState.RECOMMENDED,
            provenance=RuntimeProvenance.USER_CONFIRMED,
            source_id="MESSAGE-1",
        )


def test_knowledge_proposal_source_must_belong_to_exact_runtime():
    engine = KnowledgePolicyEngine(runtime())
    with pytest.raises(ValueError, match="does not belong to the selected runtime"):
        engine.evaluate(state(parameter()), proposal(source_id="UNLISTED-SOURCE"))

    other_runtime = CompiledKnowledgeLibrary(
        package_id="jewelai.other.runtime-policy",
        artifact_version="1.0.0",
        sources=(),
        claims=(),
        domain_knowledge=(),
        language_mappings=(),
        policies=(
            CompiledPolicy(
                policy_id="POL-OTHER-SHAPE",
                target="center_stone.shape",
                effect="Recommend a shape only inside the other runtime.",
                source_kind="INTERNAL_PRODUCT_DECISION",
                source_refs=("DEC-OTHER",),
            ),
        ),
    )
    foreign = proposal(source_id=other_runtime.policies[0].policy_id)
    with pytest.raises(ValueError, match="does not belong to the selected runtime"):
        engine.evaluate(state(parameter()), foreign)


def test_user_origin_source_does_not_require_knowledge_runtime_membership():
    current = RuntimeParameterState(
        target="center_stone.shape",
        semantic_state=RuntimeSemanticState.MISSING,
    )
    incoming = proposal(
        semantic_state=RuntimeSemanticState.EXPLICIT,
        provenance=RuntimeProvenance.USER_EXPLICIT_LATEST,
        value="oval",
        source_id="MESSAGE-OUTSIDE-KNOWLEDGE-RUNTIME",
    )
    result = KnowledgePolicyEngine(runtime()).evaluate(state(current), incoming)
    assert result.outcome == "APPLIED"
    assert result.result.provenance == RuntimeProvenance.USER_EXPLICIT_LATEST
