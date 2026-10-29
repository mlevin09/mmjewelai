"""Typed provider-neutral handoff for an authoritative Internal Final Prompt.

This boundary binds the existing prompt payload to its durable scope and lineage.  It performs no
provider translation, persistence, network access, or generation work.
"""

import hashlib
import json
from enum import StrEnum
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from jewelai_domain.models import ImmutableModel
from pydantic import StrictBool, ValidationError, model_validator

from .final_prompt import (
    FinalPromptReadiness,
    InternalFinalPrompt,
    KnowledgeReleaseReference,
)
from .models import Sha256

if TYPE_CHECKING:
    from .downstream_preparation import (
        AnyCanonicalInternalFinalPromptHandoff,
        CanonicalFinalPromptAssembly,
        CanonicalFinalPromptAssemblyV2_1,
    )

INTERNAL_FINAL_PROMPT_HANDOFF_SCHEMA_VERSION = "1.0.0"


class InternalFinalPromptHandoffErrorCode(StrEnum):
    INVALID_FINAL_OUTPUT = "invalid_final_output"


class InternalFinalPromptHandoffError(ValueError):
    """Bounded fail-closed error for invalid downstream handoff inputs."""

    def __init__(self, code: InternalFinalPromptHandoffErrorCode, detail: str):
        super().__init__(detail)
        self.code = code


class InternalFinalPromptHandoff(ImmutableModel):
    """Immutable provider-neutral envelope around one authoritative final prompt."""

    schema_version: Literal["1.0.0"] = INTERNAL_FINAL_PROMPT_HANDOFF_SCHEMA_VERSION
    organization_id: UUID
    session_id: UUID
    product_state_revision_id: UUID
    enrichment_cycle_id: UUID
    knowledge_release: KnowledgeReleaseReference
    internal_final_prompt_schema_version: Literal["1.1.0"]
    internal_final_prompt_content_hash: Sha256
    readiness: FinalPromptReadiness
    ready_for_downstream_preparation: StrictBool
    internal_final_prompt: InternalFinalPrompt
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_authoritative_binding(self):
        prompt = self.internal_final_prompt
        if (
            self.organization_id != prompt.organization_id
            or self.session_id != prompt.session_id
            or self.product_state_revision_id != prompt.product_state_revision_id
            or self.enrichment_cycle_id != prompt.enrichment_cycle_id
        ):
            raise ValueError("handoff scope or authoritative lineage mismatch")
        if self.knowledge_release != prompt.knowledge_release:
            raise ValueError("handoff Knowledge release mismatch")
        if (
            self.internal_final_prompt_schema_version != prompt.schema_version
            or self.internal_final_prompt_content_hash != prompt.content_hash
        ):
            raise ValueError("handoff Internal Final Prompt integrity mismatch")
        if self.readiness != prompt.readiness:
            raise ValueError("handoff readiness mismatch")
        expected_ready = prompt.readiness in {
            FinalPromptReadiness.READY,
            FinalPromptReadiness.READY_WITH_UNRESOLVED,
        }
        if self.ready_for_downstream_preparation != expected_ready:
            raise ValueError("handoff downstream readiness mismatch")
        if self.content_hash != _hash(self.model_dump(mode="json", exclude={"content_hash"})):
            raise ValueError("Internal Final Prompt handoff content hash mismatch")
        return self


def build_internal_final_prompt_handoff(
    final_output: "CanonicalFinalPromptAssembly | CanonicalFinalPromptAssemblyV2_1 | object",
) -> "AnyCanonicalInternalFinalPromptHandoff":
    """Validate an existing authoritative output and bind it into a deterministic handoff."""

    try:
        # Round-trip through JSON-compatible data so unchecked ``model_copy`` data is revalidated.
        if hasattr(final_output, "model_dump"):
            final_output = final_output.model_dump(mode="json")
        from .downstream_preparation import (
            CanonicalFinalPromptAssembly,
            CanonicalFinalPromptAssemblyV2_1,
            CanonicalInternalFinalPromptHandoff,
            CanonicalInternalFinalPromptHandoffV2_1,
        )

        # Exact version dispatch; no latest/default or validation-fallback probing.
        version = final_output.get("internal_final_prompt", {}).get("schema_version")
        assembly_type, handoff_type = {
            "2.0.0": (CanonicalFinalPromptAssembly, CanonicalInternalFinalPromptHandoff),
            "2.1.0": (CanonicalFinalPromptAssemblyV2_1, CanonicalInternalFinalPromptHandoffV2_1),
        }[version]
        assembly = assembly_type.model_validate(final_output)
    except (ValidationError, TypeError, ValueError, KeyError, AttributeError) as exc:
        raise InternalFinalPromptHandoffError(
            InternalFinalPromptHandoffErrorCode.INVALID_FINAL_OUTPUT,
            "authoritative final output failed handoff validation",
        ) from exc

    prompt = assembly.internal_final_prompt
    payload = {
        "schema_version": prompt.schema_version,
        "organization_id": prompt.organization_id,
        "session_id": prompt.session_id,
        "product_state_revision_id": prompt.product_state_revision_id,
        "enrichment_cycle_id": prompt.enrichment_cycle_id,
        "knowledge_release": prompt.knowledge_release,
        "internal_final_prompt_schema_version": prompt.schema_version,
        "internal_final_prompt_content_hash": prompt.content_hash,
        "readiness": prompt.readiness,
        "ready_for_downstream_preparation": prompt.readiness
        in {FinalPromptReadiness.READY, FinalPromptReadiness.READY_WITH_UNRESOLVED},
        "internal_final_prompt": prompt,
    }
    return handoff_type(**payload, content_hash=_hash(payload))


def _hash(payload: object) -> str:
    canonical = json.dumps(
        _json(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    return value
