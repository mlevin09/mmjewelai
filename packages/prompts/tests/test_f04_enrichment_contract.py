"""Explicit F04 source decoding does not reinterpret frozen legacy enrichment."""

from copy import deepcopy
from uuid import uuid4

import pytest
from jewelai_domain.clarification_state import (
    F04_PROFILE,
    EvidenceScope,
    build_availability_overlay,
    evidence_hash,
)
from pydantic import ValidationError
from test_enrichment import ring as ring
from test_enrichment import runtime as runtime
from test_enrichment import templates as templates

from jewelai_prompts import enrich_prompt
from jewelai_prompts.enrichment import (
    StructuredPromptEnrichmentResultV2,
    decode_f04_prompt_enrichment_result,
    decode_prompt_enrichment_result,
)


def payload(ring, templates, runtime):
    original = enrich_prompt(ring, templates, runtime)
    scope = EvidenceScope(organization_id=uuid4(), session_id=uuid4(), design_id=ring.design_id)
    data = original.model_dump(mode="json")
    data.update(
        enrichment_version="2.0.0",
        contract_profile=F04_PROFILE,
        scope=scope.model_dump(mode="json"),
        availability_overlay=build_availability_overlay(ring, scope=scope).model_dump(mode="json"),
        knowledge_validation_report_sha256="a" * 64,
    )
    data["context"] = dict(
        scope=scope.model_dump(mode="json"),
        contract_profile=F04_PROFILE,
        source_revision_id=str(ring.revision_id),
        source_revision_sha256=evidence_hash(ring),
        source_enrichment_cycle_id=str(uuid4()),
        source_enrichment_cycle_number=1,
        release_pin=dict(
            package_id=runtime.package_id,
            artifact_version=runtime.artifact_version,
            runtime_sha256=runtime.sha256,
            validation_report_sha256="a" * 64,
        ),
        artifact_pins=dict(
            design_schema_version=ring.schema_version,
            role_artifact_version="1.0.0",
            dictionary_artifact_version="1.0.0",
            question_schema_version="2.0.0",
            question_artifact_version="2.0.0",
            rules_schema_version="2.0.0",
            rules_artifact_version="2.0.0",
            prompt_template_artifact_version="1.0.0",
            dictionary_sha256="a" * 64,
            question_sha256="b" * 64,
            rules_sha256="c" * 64,
        ),
    )
    data["content_hash"] = evidence_hash({k: v for k, v in data.items() if k != "content_hash"})
    return original, data


def test_f04_source_exact_reader_and_legacy_bytes(ring, templates, runtime):
    original, data = payload(ring, templates, runtime)
    before = original.model_dump_json()
    parsed = decode_f04_prompt_enrichment_result(data)
    assert isinstance(parsed, StructuredPromptEnrichmentResultV2)
    assert parsed.model_dump(mode="json") == data
    assert decode_prompt_enrichment_result(original).model_dump_json() == before
    with pytest.raises(ValidationError):
        decode_prompt_enrichment_result(data)
    assert ring.revision_id == parsed.availability_overlay.canonical_revision_id


@pytest.mark.parametrize(
    "field", ("enrichment_version", "context", "scope", "availability_overlay", "contract_profile")
)
def test_f04_missing_explicit_fields_rejected(ring, templates, runtime, field):
    _, data = payload(ring, templates, runtime)
    data.pop(field)
    with pytest.raises(ValidationError):
        decode_f04_prompt_enrichment_result(data)


def test_f04_valid_checksum_cannot_hide_scope_mismatch(ring, templates, runtime):
    _, data = payload(ring, templates, runtime)
    data = deepcopy(data)
    data["scope"]["session_id"] = str(uuid4())
    data["content_hash"] = evidence_hash({k: v for k, v in data.items() if k != "content_hash"})
    with pytest.raises(ValidationError, match="context mismatch"):
        decode_f04_prompt_enrichment_result(data)


def test_parser13_pin_is_hash_bound_without_rewriting_historical_wire(ring, templates, runtime):
    _, historical = payload(ring, templates, runtime)
    original = decode_f04_prompt_enrichment_result(historical)
    current = {**historical, "parser_evidence_version": "1.3.0"}
    with pytest.raises(ValidationError, match="hash"):
        decode_f04_prompt_enrichment_result(current)
    current["content_hash"] = evidence_hash(
        {k: v for k, v in current.items() if k != "content_hash"}
    )
    checked = decode_f04_prompt_enrichment_result(current)
    assert checked.model_dump(mode="json") == current
    assert original.model_dump(mode="json") == historical
    assert checked.content_hash != original.content_hash
    current["parser_evidence_version"] = "9.0.0"
    current["content_hash"] = evidence_hash(
        {k: v for k, v in current.items() if k != "content_hash"}
    )
    with pytest.raises(ValidationError):
        decode_f04_prompt_enrichment_result(current)
