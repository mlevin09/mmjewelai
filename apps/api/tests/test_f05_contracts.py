"""Committed request-closure regressions for approved F05 R2 (not HTTP acceptance)."""

import json
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from jewelai_api.clarification_f05 import (
    ContinuationAnswerRequest,
    ContinuationResumeRequest,
    decode_continuation_command,
)


def frame():
    return dict(
        revision_id=str(uuid4()),
        revision_sha256="a" * 64,
        enrichment_cycle_id=str(uuid4()),
        enrichment_cycle_number=2,
        enrichment_result_hash="b" * 64,
        plan_id=str(uuid4()),
        plan_hash="c" * 64,
        history_root_sha256="d" * 64,
    )


def command():
    head = frame()
    return dict(
        schema_version="3.0.0",
        answer_id=str(uuid4()),
        message_id=str(uuid4()),
        expected_head=head,
        clarification_plan_id=head["plan_id"],
        clarification_id="question",
    )


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize("decision", ["SELECT_OPTION", "ACCEPT", "REJECT", "SKIP", "UNKNOWN"])
def test_all_existing_native_actions_have_an_exact_request_variant(base, decision):
    selected = decision == "SELECT_OPTION"
    native = dict(
        retained_base=base, decision=decision, selected_option="gold" if selected else None
    )
    if base == "F":
        native["selected_option_id"] = "option_" + "e" * 64 if selected else None
    data = dict(**command(), answer_kind="NATIVE", native=native)
    adapter = TypeAdapter(ContinuationAnswerRequest)
    value = adapter.validate_python(data)
    assert json.loads(value.model_dump_json()) == data
    assert adapter.validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize("decision", ["ACCEPT", "REJECT"])
def test_keep_release_is_a_distinct_typed_command(decision):
    data = dict(
        **command(),
        answer_kind="KEEP_RELEASE",
        intent_id="e" * 64,
        requested_value_sha256="f" * 64,
        decision=decision,
    )
    assert TypeAdapter(ContinuationAnswerRequest).validate_python(data).decision == decision


@pytest.mark.parametrize("decision", ["SKIP", "UNKNOWN", "SELECT_OPTION"])
def test_native_actions_cannot_be_smuggled_into_keep_release(decision):
    data = dict(
        **command(),
        answer_kind="KEEP_RELEASE",
        intent_id="e" * 64,
        requested_value_sha256="f" * 64,
        decision=decision,
    )
    with pytest.raises(ValidationError):
        TypeAdapter(ContinuationAnswerRequest).validate_python(data)


def test_missing_f_option_id_wrong_plan_and_extra_fields_fail_closed():
    data = dict(
        **command(),
        answer_kind="NATIVE",
        native=dict(
            retained_base="F",
            decision="SELECT_OPTION",
            selected_option="gold",
            selected_option_id=None,
        ),
    )
    with pytest.raises(ValidationError):
        TypeAdapter(ContinuationAnswerRequest).validate_python(data)
    data["native"].update(selected_option=None, decision="UNKNOWN")
    data["clarification_plan_id"] = str(uuid4())
    with pytest.raises(ValidationError):
        TypeAdapter(ContinuationAnswerRequest).validate_python(data)


def test_resume_native_requires_actual_f_base_and_exact_new_version():
    data = dict(
        schema_version="3.0.0",
        request_id=str(uuid4()),
        message_id=str(uuid4()),
        expected_head=frame(),
        resume_kind="NATIVE",
        retained_base="F",
        cause_id="cause",
    )
    adapter = TypeAdapter(ContinuationResumeRequest)
    assert adapter.validate_python(data).retained_base == "F"
    for key, value in [("retained_base", "L"), ("schema_version", "1.0.0")]:
        bad = {**data, key: value}
        with pytest.raises(ValidationError):
            adapter.validate_python(bad)


def test_new_wire_rejects_duplicates_coercion_and_unrecognized_keys():
    data = dict(
        **command(),
        answer_kind="NATIVE",
        native=dict(retained_base="L", decision="UNKNOWN", selected_option=None),
    )
    raw = json.dumps(data)
    assert decode_continuation_command(ContinuationAnswerRequest, raw).native.decision == "UNKNOWN"
    with pytest.raises(ValueError, match="Duplicate"):
        decode_continuation_command(
            ContinuationAnswerRequest, raw[:-1] + ', "answer_kind":"KEEP_RELEASE"}'
        )
    for bad in [
        {**data, "unapproved_authority": True},
        {**data, "schema_version": "2.0.0"},
        {**data, "expected_head": {**data["expected_head"], "enrichment_cycle_number": True}},
    ]:
        with pytest.raises(ValueError):
            decode_continuation_command(ContinuationAnswerRequest, json.dumps(bad))
    with pytest.raises(ValueError, match="finite"):
        decode_continuation_command(ContinuationAnswerRequest, '{"unexpected":NaN}')


def test_f05_actual_utf8_envelope_capacity_boundary():
    from jewelai_api.continuation_preview import ContinuationReadError
    from jewelai_api.continuation_runtime import check_capacity

    # The same canonical evidence serializer is used by the actual precommit
    # writer. Two JSON string quotes count toward the one-MiB envelope.
    limit = 1_048_576
    check_capacity("A" * (limit - 2))
    with pytest.raises(ContinuationReadError) as error:
        check_capacity("A" * (limit - 1))
    assert error.value.status == 422
    check_capacity("\U0001f600" * ((limit - 2) // 4))
    with pytest.raises(ContinuationReadError):
        check_capacity("\U0001f600" * ((limit - 2) // 4 + 1))
