"""Correction evaluation using the same current Parser as initial intake.

Versions identify immutable evidence formats, not separate extraction engines.
Canonical mutation and scoped KEEP consent remain downstream responsibilities.
"""

from datetime import UTC
from typing import Annotated, Literal

from jewelai_domain.clarification_state import Sha256
from jewelai_domain.continuation import ContinuationContext
from jewelai_domain.preservation import contract_hash
from jewelai_domain.rules import RuleDecision
from jewelai_domain.rules_v2 import RuleDecisionV2
from jewelai_parser.full_message import FullMessageParseResultV1_2, parse_full_message
from jewelai_prompts.enrichment import (
    StructuredPromptEnrichmentResult,
    StructuredPromptEnrichmentResultV2,
)
from pydantic import Field, model_validator

from .f04_planning import f04_enrichment
from .parametric_enrichment import select_parametric_references
from .parsed_enrichment import (
    ParsedCandidateEnrichmentResult,
    enrich_parsed_candidates_with_active_release,
)


class ParsedEvaluationV3(ParsedCandidateEnrichmentResult):
    evaluation_version: Literal["3.0.0"]
    context: ContinuationContext
    parse_result: FullMessageParseResultV1_2
    enrichment_result: Annotated[
        StructuredPromptEnrichmentResult | StructuredPromptEnrichmentResultV2,
        Field(discriminator="enrichment_version"),
    ]
    native_rule_decision: RuleDecisionV2 | RuleDecision
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_continuation_evidence(self):
        pin, parsed, native = self.context.release_pin, self.parse_result, self.enrichment_result
        if (
            self.context.parser_interpreter_id != "f05-1.2"
            or parsed.dictionary_artifact_version
            != self.context.artifact_pins.dictionary_artifact_version
            or (native.enrichment_version == "2.0.0") != (self.context.retained_base == "F")
            or (
                parsed.knowledge_package_id,
                parsed.knowledge_artifact_version,
                parsed.knowledge_runtime_sha256,
            )
            != (pin.package_id, pin.artifact_version, pin.runtime_sha256)
            or (
                native.knowledge_package_id,
                native.knowledge_artifact_version,
                native.knowledge_runtime_sha256,
                native.knowledge_validation_report_sha256,
            )
            != (
                pin.package_id,
                pin.artifact_version,
                pin.runtime_sha256,
                pin.validation_report_sha256,
            )
        ):
            raise ValueError("Continuation evaluation interpreter/release binding mismatch")
        if self.content_hash != contract_hash(
            "jewelai.ParsedEvaluation/3.0.0", self.model_dump(mode="json", exclude={"content_hash"})
        ):
            raise ValueError("Continuation evaluation integrity mismatch")
        return self


def evaluate_continuation_message(
    service,
    revision,
    message,
    source,
    *,
    context,
    verified_release,
    role_id,
    locale,
    native_context=None,
):
    """Evaluate actual scoped text with the admitted interpreter and existing owners.

    Native F input context identifies the real source frame, which need not equal
    the post-transition revision. Its availability overlay describes the supplied
    evaluation revision. Neither observation permits a canonical write.
    """
    timestamp = message.created_at
    timestamp = timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp
    if (
        message.actor != "user"
        or message.session_id != context.scope.session_id
        or source.message_id != str(message.message_id)
        or source.recorded_at != timestamp
        or revision.design_id != context.scope.design_id
        or revision.schema_version != context.artifact_pins.design_schema_version
    ):
        raise ValueError("Continuation evaluation requires exact scoped Message provenance")
    if context.parser_interpreter_id != "f05-1.2":
        raise ValueError("Explicit continuation interpreter is required")
    parsed = parse_full_message(
        message.content,
        locale=locale,
        dictionary=service.artifacts.dictionary,
        knowledge_runtime=verified_release.compiled_runtime,
        _result_type=FullMessageParseResultV1_2,
    )

    def build(**payload):
        native = payload["enrichment_result"]
        if context.retained_base == "F":
            if native_context is None:
                raise ValueError("F evaluation requires its actual native source context")
            native = f04_enrichment(native, revision=revision, context=native_context)
        elif native_context is not None:
            raise ValueError("L cannot acquire a native F context")
        payload.update(
            evaluation_version="3.0.0",
            context=context,
            enrichment_result=native,
            native_rule_decision=service.artifacts.rules.evaluate(revision, role_id),
        )
        return ParsedEvaluationV3(
            **payload, content_hash=contract_hash("jewelai.ParsedEvaluation/3.0.0", payload)
        )

    catalog = service.artifacts.parametric_knowledge
    return enrich_parsed_candidates_with_active_release(
        revision,
        parse_result=parsed,
        source=source,
        dictionary=service.artifacts.dictionary,
        templates=service.artifacts.prompts,
        artifact_store=service.artifact_store,
        knowledge_package_id=context.release_pin.package_id,
        knowledge_artifact_version=context.release_pin.artifact_version,
        active_release=verified_release,
        validation_report=service.validation_report,
        parametric_catalog_id=catalog.catalog_id,
        parametric_artifact_version=str(catalog.artifact_version),
        parametric_catalog_sha256=catalog.sha256,
        parametric_references=select_parametric_references(revision, catalog),
        _parse_reader=FullMessageParseResultV1_2,
        _result_builder=build,
    )


def canonical_native_result(service, revision, context, *, native_context=None):
    """Current Matrix projects committed facts; candidate evaluations remain evidence.

    An EXPLICIT numeric proposal may be Matrix-eligible while scoped consent is
    still pending. It must not replace a fact in the current Cycle3 projection.
    The existing compiler/Policy still owns Matrix construction; no cell is
    patched or assigned a fabricated acceptance/KEEP disposition here.
    """
    from jewelai_prompts import enrich_prompt_with_active_release

    native = enrich_prompt_with_active_release(
        revision,
        service.artifacts.prompts,
        service.artifact_store,
        knowledge_package_id=context.release_pin.package_id,
        knowledge_artifact_version=context.release_pin.artifact_version,
        active_release=service.active_release,
        validation_report=service.validation_report,
        proposals=(),
        **service._parametric_kwargs(revision),
    )
    if context.retained_base == "F":
        if native_context is None:
            raise ValueError("Canonical F Matrix requires actual native source context")
        return f04_enrichment(native, revision=revision, context=native_context)
    return native
