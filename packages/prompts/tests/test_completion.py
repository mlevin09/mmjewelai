from datetime import UTC, datetime
from uuid import uuid4

import pytest
from test_completion_candidate import current as current
from test_completion_candidate import dictionary as dictionary
from test_completion_candidate import ring as ring
from test_completion_candidate import runtime as runtime
from test_completion_candidate import templates as templates

from jewelai_prompts.completion import CompletionRegistry, build_completion, validate_completion


def registry():
    return CompletionRegistry.model_validate(
        dict(
            registry_id="test_only",
            version="1.0.0",
            review_status="APPROVED",
            rules=[
                dict(
                    target_path="metal.finish",
                    when_jewelry_type="ring",
                    proposed_value="polished",
                    rule_id="test_finish",
                    rule_version="1.0.0",
                    rationale="TEST ONLY",
                    requires={"metal.material": "gold"},
                )
            ],
            eligibility=[],
        )
    )


@pytest.mark.parametrize("mode", ["user_required", "default_only"])
def test_missing_mandatory_choice_cannot_be_discharged_by_no(current, templates, dictionary, mode):
    policy = registry().model_dump(mode="json")
    policy["eligibility"] = [dict(jewelry_type="ring", target="center_stone.dimensions", mode=mode)]
    with pytest.raises(ValueError, match="mandatory_decision_unresolved"):
        build_completion(
            current,
            CompletionRegistry.model_validate(policy),
            completion_id=uuid4(),
            message_id=uuid4(),
            completed_at=datetime(2026, 11, 6, tzinfo=UTC),
            dictionary=dictionary,
            templates=templates,
        )


def test_ifp6_actual_assumptions_integrity_and_user_precedence(current, templates, dictionary):
    result = build_completion(
        current,
        registry(),
        completion_id=uuid4(),
        message_id=uuid4(),
        completed_at=datetime(2026, 11, 6, tzinfo=UTC),
        dictionary=dictionary,
        templates=templates,
    )
    assert result.schema_version == "6.0.0"
    assert result.assumptions and result.assumptions[0].origin == "AI_DEFAULT"
    assert result.effective_revision.design.metal.finish.origin == "assumed"
    assert not result.effective_revision.design.metal.finish.confirmed
    assert validate_completion(result.model_dump(mode="json"), templates) == result
    assert current.revision.design.metal.finish is None
    payload = result.model_dump(mode="json")
    payload["prompt_text"] += " tamper"
    with pytest.raises(ValueError):
        validate_completion(payload, templates)
    with pytest.raises(ValueError, match="Unapproved"):
        build_completion(
            current,
            registry().model_copy(update={"review_status": "PROPOSED"}),
            completion_id=uuid4(),
            message_id=uuid4(),
            completed_at=result.completed_at,
            dictionary=dictionary,
            templates=templates,
        )


@pytest.mark.parametrize(
    "field,value",
    [("readiness", "READY"), ("omitted_targets", ["metal.material"]), ("policy_sha256", "0" * 64)],
)
def test_ifp6_rehashed_semantic_tamper_rejected(current, templates, dictionary, field, value):
    from jewelai_domain.preservation import contract_hash

    result = build_completion(
        current,
        registry(),
        completion_id=uuid4(),
        message_id=uuid4(),
        completed_at=datetime(2026, 11, 6, tzinfo=UTC),
        dictionary=dictionary,
        templates=templates,
    )
    payload = result.model_dump(mode="json")
    if field == "readiness" and payload[field] == value:
        value = "READY_WITH_UNRESOLVED"
    payload[field] = value
    payload["content_hash"] = contract_hash(
        "jewelai.InternalFinalPrompt/6.0.0",
        {k: v for k, v in payload.items() if k != "content_hash"},
    )
    with pytest.raises(ValueError):
        validate_completion(payload, templates)


def test_ifp6_does_not_override_locked_user_value(current, templates, dictionary):
    from jewelai_prompts.completion import CompletionRule

    r = registry()
    color = CompletionRule(
        target_path="metal.color",
        when_jewelry_type="ring",
        proposed_value="yellow",
        rule_id="test_color",
        rule_version="1.0.0",
        rationale="TEST ONLY",
        requires={},
    )
    r = type(r).model_validate({**r.model_dump(), "rules": (*r.rules, color)})
    result = build_completion(
        current,
        r,
        completion_id=uuid4(),
        message_id=uuid4(),
        completed_at=datetime(2026, 11, 6, tzinfo=UTC),
        dictionary=dictionary,
        templates=templates,
    )
    assert result.effective_revision.design.metal.color == current.revision.design.metal.color
    assert current.revision.design.metal.color.locked
    assert not any(a.target_path == "metal.color" for a in result.assumptions)
    constraints = result.prompt_text.split("ACTIVE CONSTRAINTS — MUST PRESERVE\n")[1]
    locked = [line for line in constraints.splitlines() if "locked value must not change" in line]
    assert len(locked) == 1
    assert 'metal.color: "white"' in locked[0]


def test_ifp6_field_keep_names_current_target_and_value(current, templates, dictionary):
    from jewelai_prompts.completion import _render
    from jewelai_prompts.final_prompt import FinalPromptConstraint

    result = build_completion(
        current,
        registry(),
        completion_id=uuid4(),
        message_id=uuid4(),
        completed_at=current.revision.created_at,
        dictionary=dictionary,
        templates=templates,
    )
    text = _render(
        result.effective_parameters,
        (
            FinalPromptConstraint(
                kind="preservation",
                target="center_stone.shape",
                instruction="Keep this current authoritative center-stone field unchanged.",
            ),
        ),
        (),
    )
    line = text.split("ACTIVE CONSTRAINTS — MUST PRESERVE\n")[1].splitlines()[0]
    assert 'center_stone.shape: "oval"' in line
    assert "unchanged" in line
