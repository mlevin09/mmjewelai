"""F04 typed evidence uses actual deterministic source parsing; no state update authority."""

import hashlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from jewelai_domain import load_domain_dictionary
from jewelai_domain.clarification_state import (
    F04_PROFILE,
    ArtifactPins,
    EvidenceScope,
    InputContext,
    ReleasePin,
)
from jewelai_parser import parse_full_message
from test_parsed_enrichment import collision_release as collision_release
from test_parsed_enrichment import dictionary as dictionary

from jewelai_api.conflict_evidence import product_body_material_conflict

ROOT = Path(__file__).resolve().parents[3]


def context(dictionary):
    return InputContext(
        scope=EvidenceScope(organization_id=uuid4(), session_id=uuid4(), design_id=uuid4()),
        contract_profile=F04_PROFILE,
        source_revision_id=uuid4(),
        source_revision_sha256="a" * 64,
        source_enrichment_cycle_id=uuid4(),
        source_enrichment_cycle_number=1,
        release_pin=ReleasePin(
            package_id="test",
            artifact_version="1.0.0",
            runtime_sha256="a" * 64,
            validation_report_sha256="b" * 64,
        ),
        artifact_pins=ArtifactPins(
            design_schema_version="1.1.0",
            role_artifact_version="1.0.0",
            dictionary_artifact_version=dictionary.artifact_version,
            question_schema_version="2.0.0",
            question_artifact_version="2.0.0",
            rules_schema_version="2.0.0",
            rules_artifact_version="2.0.0",
            prompt_template_artifact_version="1.0.0",
            dictionary_sha256=hashlib.sha256(
                (ROOT / "data/dictionary/v1.0.0.json").read_bytes()
            ).hexdigest(),
            question_sha256=hashlib.sha256(
                (ROOT / "data/questions/v2.0.0.json").read_bytes()
            ).hexdigest(),
            rules_sha256=hashlib.sha256((ROOT / "data/rules/v2.0.0.json").read_bytes()).hexdigest(),
        ),
    )


@pytest.mark.parametrize(
    "text,locale,kind",
    (
        ("Gold or platinum ring with an oval diamond.", "en", "alternative"),
        ("Gold and platinum ring.", "en", "competing"),
        ("A gold ring with gold metal.", "en", "equivalent"),
        ("Кольцо из золота или платины с овальным алмазом.", "ru", "alternative"),
        ("Кольцо из золота и платины.", "ru", "competing"),
        ("Кольцо из золота. Металл — золото.", "ru", "equivalent"),
        ("Gold или платина.", "ru", "alternative"),
        ("Gold body. Platinum body.", "en", "competing"),
        ("A platinum ring. Platinum metal.", "en", "equivalent"),
        ("Gold or platinum or gold ring.", "en", "alternative"),
        ("Gold or gold ring.", "en", "equivalent"),
    ),
)
def test_actual_source_conflict_evidence(text, locale, kind):
    dictionary = load_domain_dictionary(ROOT / "data/dictionary/v1.0.0.json")
    parsed = parse_full_message(text, locale=locale, dictionary=dictionary)
    ctx = context(dictionary)
    message = source_message(text, ctx)
    actual = product_body_material_conflict(
        parsed, message=message, context=ctx, dictionary=dictionary
    )
    assert actual is not None
    assert actual.kind == kind
    assert (
        product_body_material_conflict(parsed, message=message, context=ctx, dictionary=dictionary)
        == actual
    )
    assert all(
        text[o.evidence_start : o.evidence_end] == o.evidence_text for o in actual.occurrences
    )
    assert all(o.message_id == message.message_id for o in actual.occurrences)
    assert len(actual.occurrences) == (3 if text == "Gold or platinum or gold ring." else 2)
    assert actual.target.concrete_target == "metal.material"


@pytest.mark.parametrize(
    "text,locale",
    (
        ("Platinum shank with rose-gold prongs.", "en"),
        ("No gold or platinum.", "en"),
        ("I prefer gold or platinum.", "en"),
        ("Maybe gold or platinum.", "en"),
        ("Хочу золото или платину.", "ru"),
        ("A gold ring with platinum prongs.", "en"),
        ("A gold ring. No gold prongs.", "en"),
    ),
)
def test_negation_uncertainty_preference_and_components_do_not_gain_authority(text, locale):
    dictionary = load_domain_dictionary(ROOT / "data/dictionary/v1.0.0.json")
    parsed = parse_full_message(text, locale=locale, dictionary=dictionary)
    ctx = context(dictionary)
    assert (
        product_body_material_conflict(
            parsed,
            message=source_message(text, ctx),
            context=ctx,
            dictionary=dictionary,
        )
        is None
    )


def test_forged_normalization_cannot_be_blessed_by_checksum():
    dictionary = load_domain_dictionary(ROOT / "data/dictionary/v1.0.0.json")
    text = "A gold ring with gold metal."
    parsed = parse_full_message(text, locale="en", dictionary=dictionary)
    data = parsed.model_dump(mode="json")
    data["candidates"][0]["normalized_values"] = ["platinum"]
    ctx = context(dictionary)
    with pytest.raises(ValueError, match="deterministic source parsing"):
        product_body_material_conflict(
            data,
            message=source_message(text, ctx),
            context=ctx,
            dictionary=dictionary,
        )


def source_message(text, ctx):
    return SimpleNamespace(
        content=text, message_id=uuid4(), session_id=ctx.scope.session_id, actor="user"
    )


def test_knowledge_mirror_cannot_add_explicit_material_authority(collision_release):
    _, _, compiled, _, active = collision_release
    dictionary = load_domain_dictionary(ROOT / "data/dictionary/v1.0.0.json")
    text = "Gold or platinum ring."
    parsed = parse_full_message(
        text, locale="en", dictionary=dictionary, knowledge_runtime=compiled
    )
    raw = context(dictionary).model_dump(mode="json")
    raw["release_pin"] = dict(
        package_id=active.package_id,
        artifact_version=active.artifact_version,
        runtime_sha256=active.runtime_sha256,
        validation_report_sha256=active.validation_report_sha256,
    )
    ctx = InputContext.model_validate(raw)
    conflict = product_body_material_conflict(
        parsed,
        message=source_message(text, ctx),
        context=ctx,
        dictionary=dictionary,
        knowledge_runtime=compiled,
    )
    assert conflict is not None and len(conflict.occurrences) == 2
    assert all(o.normalization_source == "domain_dictionary" for o in conflict.occurrences)
    assert len(parsed.candidates) > len(conflict.occurrences)


def test_source_knowledge_identity_cannot_be_swapped(collision_release):
    _, _, compiled, _, _ = collision_release
    dictionary = load_domain_dictionary(ROOT / "data/dictionary/v1.0.0.json")
    text = "Gold or platinum ring."
    parsed = parse_full_message(
        text, locale="en", dictionary=dictionary, knowledge_runtime=compiled
    )
    ctx = context(dictionary)
    with pytest.raises(ValueError, match="Knowledge release pin"):
        product_body_material_conflict(
            parsed,
            message=source_message(text, ctx),
            context=ctx,
            dictionary=dictionary,
            knowledge_runtime=compiled,
        )


@pytest.mark.parametrize("foreign", ("actor", "session"))
def test_source_scope_cannot_be_replaced(foreign):
    dictionary = load_domain_dictionary(ROOT / "data/dictionary/v1.0.0.json")
    text = "Gold or platinum ring."
    ctx = context(dictionary)
    message = source_message(text, ctx)
    if foreign == "actor":
        message.actor = "assistant"
    else:
        message.session_id = uuid4()
    with pytest.raises(ValueError, match="actor/session scope"):
        product_body_material_conflict(
            parse_full_message(text, locale="en", dictionary=dictionary),
            message=message,
            context=ctx,
            dictionary=dictionary,
        )
