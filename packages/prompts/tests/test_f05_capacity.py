"""F05-only overflow translation; real persisted boundaries live in API tests."""

from uuid import uuid4

import pytest
from jewelai_domain.clarification_state import evidence_hash
from pydantic import ValidationError

from jewelai_prompts import final_prompt_v4
from jewelai_prompts.downstream_preparation import GenerationPreparationError, PreparationErrorCode
from jewelai_prompts.final_prompt import UserReadableJewelryDescription
from jewelai_prompts.final_prompt_v3 import UserReadableJewelryDescriptionV2


def payload():
    body = dict(
        schema_version="2.0.0",
        locale="en",
        authoritative_revision_id=str(uuid4()),
        text="Synthetic current description.",
        unresolved_summary=[],
        effective_frontier_hash="1" * 64,
    )
    return {**body, "content_hash": evidence_hash(body)}


def test_only_actual_native_description_text_overflow_becomes_f05_capacity(monkeypatch):
    body = {**payload(), "text": "PRIVATE-SYNTHETIC-SOURCE" * 1000}

    def native(*args):
        return UserReadableJewelryDescriptionV2.model_validate(body)

    monkeypatch.setattr(final_prompt_v4, "f04_current_components", native)
    with pytest.raises(GenerationPreparationError) as caught:
        final_prompt_v4._current_f_components(None, None, None, None)
    assert caught.value.code == PreparationErrorCode.CAPACITY
    assert "PRIVATE-SYNTHETIC-SOURCE" not in str(caught.value)
    assert caught.value.__suppress_context__
    # Historical F still exposes its own unchanged structural validation.
    with pytest.raises(ValidationError):
        native()


@pytest.mark.parametrize("kind", ["wrong_model", "integrity", "multiple_errors"])
def test_other_native_validation_failures_are_not_misclassified(monkeypatch, kind):
    body = payload()
    model = UserReadableJewelryDescriptionV2
    if kind == "wrong_model":
        model = UserReadableJewelryDescription
        body.update(schema_version="1.0.0", text="x" * 20001)
        body.pop("effective_frontier_hash")
    elif kind == "integrity":
        body["content_hash"] = "0" * 64
    else:
        body.update(text="x" * 20001, locale="unsupported")

    def native(*args):
        return model.model_validate(body)

    monkeypatch.setattr(final_prompt_v4, "f04_current_components", native)
    with pytest.raises(ValidationError) as caught:
        final_prompt_v4._current_f_components(None, None, None, None)
    assert not isinstance(caught.value, GenerationPreparationError)


def test_nonstructural_native_integrity_failure_propagates(monkeypatch):
    original = ValueError("Synthetic invalid source binding")

    def native(*args):
        raise original

    monkeypatch.setattr(final_prompt_v4, "f04_current_components", native)
    with pytest.raises(ValueError) as caught:
        final_prompt_v4._current_f_components(None, None, None, None)
    assert caught.value is original


def test_valid_native_components_are_returned_without_replacement(monkeypatch):
    description = UserReadableJewelryDescriptionV2.model_validate(payload())
    result = (description, (), "ready")
    monkeypatch.setattr(final_prompt_v4, "f04_current_components", lambda *args: result)
    assert final_prompt_v4._current_f_components(None, None, None, None) is result
