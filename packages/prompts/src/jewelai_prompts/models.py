"""Immutable Prompt Compiler v1 contracts."""

from typing import Annotated, Literal
from uuid import UUID

from jewelai_domain.models import ImmutableModel, Text, Version
from pydantic import Field, JsonValue, StringConstraints, model_validator

PROMPT_SCHEMA_VERSION = "1.0.0"
PROMPT_COMPILER_VERSION = "1.0.0"
PromptId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,79}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class TemplateLabels(ImmutableModel):
    specification: Text
    locked_constraints: Text
    disclosures: Text


class TemplateProvenance(ImmutableModel):
    source_kind: Literal["repository_spec"] = "repository_spec"
    source_ref: Text
    review_status: Literal["proposed_pending_product_review"]


class PromptTemplate(ImmutableModel):
    template_id: PromptId
    template_version: Version
    purpose: Literal["jewelry_visualization"]
    output_language: Literal["en"]
    introduction: Text
    instructions: Annotated[tuple[Text, ...], Field(min_length=1)]
    labels: TemplateLabels


class PromptTemplateBundle(ImmutableModel):
    schema_version: Literal["1.0.0"]
    artifact_version: Version
    provenance: TemplateProvenance
    templates: Annotated[tuple[PromptTemplate, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_bundle(self):
        ids = [item.template_id for item in self.templates]
        if len(set(ids)) != len(ids):
            raise ValueError("Prompt template IDs must be unique")
        if list(self.templates) != sorted(self.templates, key=lambda item: item.template_id):
            raise ValueError("Prompt templates must use stable template ID order")
        return self


class SpecificationEntry(ImmutableModel):
    concrete_target: Text
    applicability: Literal["value", "not_applicable"]
    value: JsonValue = None
    origin: Literal["explicit", "derived", "assumed"]
    confirmed: bool
    locked: bool

    @model_validator(mode="after")
    def validate_value(self):
        if self.applicability == "not_applicable" and self.value is not None:
            raise ValueError("Not-applicable entries cannot carry a value")
        if self.applicability == "value" and self.value is None:
            raise ValueError("Value entries must carry a value")
        return self


class PromptConstraint(ImmutableModel):
    concrete_target: Text
    applicability: Literal["value", "not_applicable"]
    value: JsonValue = None


class PromptSourceReference(ImmutableModel):
    kind: Literal["knowledge", "rule"]
    identifier: Text
    version: Version


class PromptDisclosure(ImmutableModel):
    concrete_target: Text
    origin: Literal["derived", "assumed", "not_applicable"]
    uncertainty: Text | None = None
    rationale: Text | None = None
    reason: Text | None = None
    sources: tuple[PromptSourceReference, ...] = ()

    @model_validator(mode="after")
    def validate_disclosure(self):
        expected = {
            "derived": self.uncertainty is not None and bool(self.sources),
            "assumed": self.rationale is not None and len(self.sources) == 1,
            "not_applicable": self.reason is not None and not self.sources,
        }
        if not expected[self.origin]:
            raise ValueError(f"Incomplete {self.origin} disclosure")
        return self


class CompiledPrompt(ImmutableModel):
    schema_version: Literal["1.0.0"] = PROMPT_SCHEMA_VERSION
    compiler_version: Literal["1.0.0"] = PROMPT_COMPILER_VERSION
    template_id: PromptId
    template_version: Version
    template_artifact_version: Version
    specification_revision_id: UUID
    design_id: UUID
    design_schema_version: Version
    prompt_text: Text
    specification_entries: tuple[SpecificationEntry, ...]
    locked_constraints: tuple[PromptConstraint, ...]
    disclosures: tuple[PromptDisclosure, ...]
    content_hash: Sha256
