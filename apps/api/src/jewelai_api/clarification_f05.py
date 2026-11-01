"""Exact F05 command wire variants; frozen L/F request types stay unchanged."""

import json
from typing import Annotated, Literal
from uuid import UUID

from jewelai_domain.clarification_state import Sha256, StrictEvidenceModel
from jewelai_domain.continuation import ContinuationFrame
from pydantic import Field, TypeAdapter, model_validator

from .clarification_answers import ClarificationDecision


class ContinuationAdmissionRequest(StrictEvidenceModel):
    schema_version: Literal["1.0.0"]
    request_id: UUID
    message_id: UUID
    expected_head: ContinuationFrame


class ContinuationCorrectionRequest(StrictEvidenceModel):
    schema_version: Literal["3.0.0"]
    request_id: UUID
    message_id: UUID
    expected_head: ContinuationFrame


class NativeLAnswer(StrictEvidenceModel):
    retained_base: Literal["L"]
    decision: ClarificationDecision
    selected_option: str | None

    @model_validator(mode="after")
    def validate_selection(self):
        if (self.decision == "SELECT_OPTION") != (self.selected_option is not None):
            raise ValueError("Only SELECT_OPTION requires an offered native value")
        return self


class NativeFAnswer(StrictEvidenceModel):
    retained_base: Literal["F"]
    decision: ClarificationDecision
    selected_option: str | None
    selected_option_id: str | None

    @model_validator(mode="after")
    def validate_selection(self):
        selected = self.decision == "SELECT_OPTION"
        if (self.selected_option is not None) != selected or (
            self.selected_option_id is not None
        ) != selected:
            raise ValueError("SELECT_OPTION requires the exact native offered ID and value")
        return self


class _AnswerCommand(StrictEvidenceModel):
    schema_version: Literal["3.0.0"]
    answer_id: UUID
    message_id: UUID
    expected_head: ContinuationFrame
    clarification_plan_id: UUID
    clarification_id: str

    @model_validator(mode="after")
    def validate_plan(self):
        if self.clarification_plan_id != self.expected_head.plan_id:
            raise ValueError("Answer plan differs from its exact expected frame")
        return self


class KeepReleaseAnswerRequest(_AnswerCommand):
    answer_kind: Literal["KEEP_RELEASE"]
    intent_id: Sha256
    requested_value_sha256: Sha256
    decision: Literal["ACCEPT", "REJECT"]


class NativeAnswerRequest(_AnswerCommand):
    answer_kind: Literal["NATIVE"]
    native: Annotated[NativeLAnswer | NativeFAnswer, Field(discriminator="retained_base")]


ContinuationAnswerRequest = Annotated[
    KeepReleaseAnswerRequest | NativeAnswerRequest, Field(discriminator="answer_kind")
]


class NativeResumeRequest(ContinuationCorrectionRequest):
    resume_kind: Literal["NATIVE"]
    retained_base: Literal["F"]
    cause_id: str


class KeepReleaseResumeRequest(ContinuationCorrectionRequest):
    resume_kind: Literal["KEEP_RELEASE"]
    intent_id: Sha256


ContinuationResumeRequest = Annotated[
    NativeResumeRequest | KeepReleaseResumeRequest, Field(discriminator="resume_kind")
]


def decode_continuation_command(request_type, raw_json):
    """Strict root JSON entry point; TypeAdapter alone cannot detect duplicate keys."""

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate continuation command key")
            result[key] = value
        return result

    def invalid_number(_):
        raise ValueError("Continuation command requires finite numbers")

    value = json.loads(raw_json, object_pairs_hook=unique_pairs, parse_constant=invalid_number)
    return TypeAdapter(request_type).validate_python(value)
