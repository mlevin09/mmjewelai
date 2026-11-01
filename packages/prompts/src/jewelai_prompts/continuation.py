"""Exact F05 enrichment envelope, retaining native evidence without relabelling it."""

from typing import Annotated, Literal

from jewelai_domain.clarification_state import Sha256, StrictEvidenceModel
from jewelai_domain.continuation import ContinuationContext
from jewelai_domain.preservation import ProtectionProjection, contract_hash
from pydantic import Field, model_validator

from .enrichment import StructuredPromptEnrichmentResult, StructuredPromptEnrichmentResultV2


class NativeLEnrichment(StrictEvidenceModel):
    retained_base: Literal["L"]
    result: StructuredPromptEnrichmentResult


class NativeFEnrichment(StrictEvidenceModel):
    retained_base: Literal["F"]
    result: StructuredPromptEnrichmentResultV2


class ContinuationEnrichmentResult(StrictEvidenceModel):
    enrichment_version: Literal["3.0.0"]
    context: ContinuationContext
    design_revision_id: str
    knowledge_package_id: str
    knowledge_artifact_version: str
    knowledge_runtime_sha256: Sha256
    knowledge_validation_report_sha256: Sha256
    native_result: Annotated[
        NativeLEnrichment | NativeFEnrichment, Field(discriminator="retained_base")
    ]
    protection_projection: ProtectionProjection
    content_hash: Sha256

    @property
    def native(self):
        return self.native_result.result

    def __getattr__(self, name):
        if name in {
            "parametric_catalog_id",
            "parametric_artifact_version",
            "parametric_catalog_sha256",
            "parametric_references",
            "initial_matrix",
            "decisions",
            "final_matrix",
            "specification_entries",
            "locked_constraints",
            "disclosures",
            "prompt_template_artifact_version",
            "availability_overlay",
        }:
            return getattr(self.native, name)
        return super().__getattr__(name)

    @model_validator(mode="after")
    def validate_cycle(self):
        native, pin, protection = self.native, self.context.release_pin, self.protection_projection
        identity = (
            self.knowledge_package_id,
            self.knowledge_artifact_version,
            self.knowledge_runtime_sha256,
            self.knowledge_validation_report_sha256,
        )
        if (
            self.native_result.retained_base != self.context.retained_base
            or self.design_revision_id != native.design_revision_id
            or identity
            != (
                pin.package_id,
                pin.artifact_version,
                pin.runtime_sha256,
                pin.validation_report_sha256,
            )
            or identity
            != (
                native.knowledge_package_id,
                native.knowledge_artifact_version,
                native.knowledge_runtime_sha256,
                native.knowledge_validation_report_sha256,
            )
            or protection.scope != self.context.scope
            or str(protection.current_revision_id) != self.design_revision_id
            or protection.design_schema_version != self.context.artifact_pins.design_schema_version
        ):
            raise ValueError("Continuation cycle native/context/protection binding mismatch")
        if self.context.parser_interpreter_id != "f05-1.2":
            raise ValueError("Continuation cycle requires the explicitly admitted interpreter")
        if self.context.retained_base == "F" and (
            native.context.scope != self.context.scope
            or native.context.artifact_pins.model_dump() != self.context.artifact_pins.model_dump()
        ):
            raise ValueError("Continuation cycle has inconsistent native F context")
        if self.content_hash != contract_hash(
            "jewelai.CycleResult/3.0.0", self.model_dump(mode="json", exclude={"content_hash"})
        ):
            raise ValueError("Continuation cycle integrity mismatch")
        return self


def continuation_cycle(context, native, protection):
    payload = dict(
        enrichment_version="3.0.0",
        context=context,
        design_revision_id=native.design_revision_id,
        knowledge_package_id=native.knowledge_package_id,
        knowledge_artifact_version=native.knowledge_artifact_version,
        knowledge_runtime_sha256=native.knowledge_runtime_sha256,
        knowledge_validation_report_sha256=native.knowledge_validation_report_sha256,
        native_result=dict(retained_base=context.retained_base, result=native),
        protection_projection=protection,
    )
    return ContinuationEnrichmentResult(
        **payload, content_hash=contract_hash("jewelai.CycleResult/3.0.0", payload)
    )
