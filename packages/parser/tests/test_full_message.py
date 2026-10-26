import json
from pathlib import Path

import pytest
from jewelai_domain import DesignRevision, compile_knowledge_library, load_domain_dictionary
from jewelai_domain.knowledge_library import (
    CompiledDomainKnowledge,
    CompiledKnowledgeLibrary,
    CompiledLanguageMapping,
    MappingMode,
    MappingQuality,
)
from pydantic import ValidationError

from jewelai_parser import (
    CandidateApplication,
    CandidateCertainty,
    CandidateClassification,
    CandidateSubject,
    FullMessageParseResult,
    MessageLanguage,
    NormalizationSource,
    StructuredTarget,
    parse_full_message,
)

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def dictionary():
    return load_domain_dictionary(ROOT / "data" / "dictionary" / "v1.0.0.json")


@pytest.fixture(scope="module")
def collision_runtime():
    # Compile the repository catalog without promoting/activating a release.
    payload = json.loads((ROOT / "data/knowledge/v1/jewelry-core-1.0.0.json").read_text())
    runtime, _ = compile_knowledge_library(payload)
    return runtime


def _dictionary_evidence(result):
    return tuple(
        candidate.model_dump(mode="json", exclude={"candidate_id"})
        for candidate in result.candidates
        if candidate.normalization_source == NormalizationSource.DOMAIN_DICTIONARY
    )


def test_dictionary_updates_survive_identical_knowledge_surfaces(dictionary, collision_runtime):
    text = "Gold ring with an oval diamond"
    baseline = parse_full_message(text, locale="en", dictionary=dictionary)
    combined = parse_full_message(
        text, locale="en", dictionary=dictionary, knowledge_runtime=collision_runtime
    )

    assert len([item for item in baseline.candidates if item.parser_update is not None]) == 4
    assert _dictionary_evidence(combined) == _dictionary_evidence(baseline)
    assert len([item for item in combined.candidates if item.parser_update is not None]) == 4
    assert (
        len(
            {
                item.parser_update.concrete_target
                for item in combined.candidates
                if item.parser_update
            }
        )
        == 4
    )
    knowledge = [
        item
        for item in combined.candidates
        if item.normalization_source == NormalizationSource.KNOWLEDGE_LIBRARY
    ]
    assert len(knowledge) == 4
    assert all(
        item.application == CandidateApplication.STRUCTURED_EVIDENCE_ONLY for item in knowledge
    )
    assert all(item.parser_update is None for item in knowledge)
    assert all(item.certainty == CandidateCertainty.EXPLICIT for item in combined.candidates)


@pytest.mark.parametrize(
    ("locale", "text"),
    [
        ("en", "A white gold ring with an emerald-cut center diamond."),
        ("ru", "Кольцо из золота с овальным алмазом."),
        ("ru", "Кольцо with gold and an oval алмаз."),
        ("en", "Gold or platinum ring."),
        ("en", "Gold ring. No halo. Keep the center stone unchanged."),
        ("ru", "Кольцо из золота. Без гало."),
        ("en", "Gold prongs and platinum body."),
        ("en", "Gold ring with gold band."),
        ("en", "Gold ring with an oval sapphire and aurora facets."),
    ],
)
def test_catalog_recognition_is_additive_and_deterministic(
    dictionary, collision_runtime, locale, text
):
    baseline = parse_full_message(text, locale=locale, dictionary=dictionary)
    combined = parse_full_message(
        text, locale=locale, dictionary=dictionary, knowledge_runtime=collision_runtime
    )
    assert _dictionary_evidence(combined) == _dictionary_evidence(baseline)
    assert combined == parse_full_message(
        text, locale=locale, dictionary=dictionary, knowledge_runtime=collision_runtime
    )
    ids = [item.candidate_id for item in combined.candidates]
    assert len(ids) == len(set(ids))
    for candidate in combined.candidates:
        span = candidate.evidence
        assert text[span.start : span.end] == span.text
        if candidate.normalization_source == NormalizationSource.KNOWLEDGE_LIBRARY:
            assert candidate.parser_update is None
        if candidate.classification in {
            CandidateClassification.PROHIBITION,
            CandidateClassification.PRESERVATION,
        }:
            assert candidate.parser_update is None
    assert not any(
        item.target == StructuredTarget.CENTER_STONE_DIMENSIONS for item in combined.candidates
    )


def _test_knowledge_terms(terms):
    return CompiledKnowledgeLibrary(
        package_id="jewelai.test.collision",
        artifact_version="1.0.0",
        sources=(),
        claims=(),
        domain_knowledge=tuple(
            CompiledDomainKnowledge(
                concept_id=concept_id,
                kind=kind,
                parent_id=None,
                relationships=(),
                claim_ids=(),
                structural_schema=True,
            )
            for concept_id, kind, _ in terms
        ),
        language_mappings=tuple(
            CompiledLanguageMapping(
                mapping_id=f"LANG-COLLISION-{index}",
                concept_id=concept_id,
                locale="en",
                canonical_term=term,
                aliases=(),
                mapping_mode=MappingMode.DIRECT,
                mapping_quality=MappingQuality.EXACT,
                context=None,
            )
            for index, (concept_id, _, term) in enumerate(terms)
        ),
        policies=(),
    )


def test_distinct_knowledge_ids_do_not_displace_dictionary_or_create_choices(dictionary):
    runtime = _test_knowledge_terms(
        (("metal.gold", "metal_material", "gold"), ("metal.platinum", "metal_material", "platinum"))
    )
    for text in ("Gold ring.", "Gold or platinum ring."):
        baseline = parse_full_message(text, locale="en", dictionary=dictionary)
        combined = parse_full_message(
            text, locale="en", dictionary=dictionary, knowledge_runtime=runtime
        )
        assert _dictionary_evidence(combined) == _dictionary_evidence(baseline)
        metals = [
            item for item in combined.candidates if item.target == StructuredTarget.METAL_MATERIAL
        ]
        assert {item.normalization_source for item in metals} == {
            NormalizationSource.DOMAIN_DICTIONARY,
            NormalizationSource.KNOWLEDGE_LIBRARY,
        }
        assert {item.certainty for item in metals} == {
            CandidateCertainty.AMBIGUOUS if " or " in text else CandidateCertainty.EXPLICIT
        }
        assert all(item.parser_update is None for item in metals if " or " in text)


def test_compound_knowledge_surface_cannot_hide_dictionary_subspans(dictionary):
    runtime = _test_knowledge_terms(
        (("gold", "metal_material", "gold"), ("white_gold", "metal_material", "white gold"))
    )
    text = "White gold ring."
    baseline = parse_full_message(text, locale="en", dictionary=dictionary)
    combined = parse_full_message(
        text, locale="en", dictionary=dictionary, knowledge_runtime=runtime
    )
    assert _dictionary_evidence(combined) == _dictionary_evidence(baseline)
    knowledge = [
        item
        for item in combined.candidates
        if item.normalization_source == NormalizationSource.KNOWLEDGE_LIBRARY
    ]
    assert len(knowledge) == 1
    assert knowledge[0].evidence.text == "White gold"
    assert knowledge[0].normalized_values == ("white_gold",)
    assert knowledge[0].parser_update is None


def test_component_and_unknown_evidence_remain_non_authoritative(dictionary, collision_runtime):
    result = parse_full_message(
        "Gold prongs and platinum body, with sapphire and aurora facets.",
        locale="en",
        dictionary=dictionary,
        knowledge_runtime=collision_runtime,
    )
    metals = [item for item in result.candidates if item.target == StructuredTarget.METAL_MATERIAL]
    assert {item.normalized_values for item in metals} == {("gold",), ("platinum",)}
    assert all(item.parser_update is None for item in metals)
    sapphire = _find(result, text="sapphire")
    assert sapphire.normalization_source == NormalizationSource.KNOWLEDGE_LIBRARY
    assert sapphire.parser_update is None
    assert _find(result, text="aurora").certainty == CandidateCertainty.UNRESOLVED
    assert _find(result, text="facets").certainty == CandidateCertainty.UNRESOLVED


def test_emerald_cut_diamond_and_white_gold_remain_distinct_facts(dictionary, collision_runtime):
    result = parse_full_message(
        "A white gold ring with an emerald-cut center diamond.",
        locale="en",
        dictionary=dictionary,
        knowledge_runtime=collision_runtime,
    )
    values = {
        item.target: item.normalized_values
        for item in result.candidates
        if item.parser_update is not None
    }
    assert values == {
        StructuredTarget.JEWELRY_TYPE: ("ring",),
        StructuredTarget.METAL_MATERIAL: ("gold",),
        StructuredTarget.METAL_COLOR: ("white",),
        StructuredTarget.CENTER_STONE_SHAPE: ("emerald_cut",),
        StructuredTarget.CENTER_STONE_MATERIAL: ("diamond",),
    }


@pytest.fixture(scope="module")
def terminology():
    concepts = (
        CompiledDomainKnowledge(
            concept_id="stone.material.sapphire",
            kind="gemstone_material",
            parent_id=None,
            relationships=(),
            claim_ids=(),
            structural_schema=True,
        ),
        CompiledDomainKnowledge(
            concept_id="stone.shape.round",
            kind="stone_shape",
            parent_id=None,
            relationships=(),
            claim_ids=(),
            structural_schema=True,
        ),
    )
    mappings = (
        CompiledLanguageMapping(
            mapping_id="LANG-SAPPHIRE-EN",
            concept_id="stone.material.sapphire",
            locale="en",
            canonical_term="sapphire",
            aliases=(),
            mapping_mode=MappingMode.DIRECT,
            mapping_quality=MappingQuality.EXACT,
            context=None,
        ),
        CompiledLanguageMapping(
            mapping_id="LANG-SAPPHIRE-RU",
            concept_id="stone.material.sapphire",
            locale="ru",
            canonical_term="сапфир",
            aliases=(),
            mapping_mode=MappingMode.DIRECT,
            mapping_quality=MappingQuality.PREFERRED,
            context=None,
        ),
        CompiledLanguageMapping(
            mapping_id="LANG-ROUND-EN",
            concept_id="stone.shape.round",
            locale="en",
            canonical_term="round",
            aliases=(),
            mapping_mode=MappingMode.DIRECT,
            mapping_quality=MappingQuality.EXACT,
            context=None,
        ),
        CompiledLanguageMapping(
            mapping_id="LANG-ROUND-RU",
            concept_id="stone.shape.round",
            locale="ru",
            canonical_term="круглый",
            aliases=(),
            mapping_mode=MappingMode.DIRECT,
            mapping_quality=MappingQuality.PREFERRED,
            context=None,
        ),
    )
    return CompiledKnowledgeLibrary(
        package_id="jewelai.test.full_message",
        artifact_version="1.0.0",
        sources=(),
        claims=(),
        domain_knowledge=concepts,
        language_mappings=mappings,
        policies=(),
    )


def _find(result, *, target=None, subject=None, classification=None, text=None):
    matches = [
        item
        for item in result.candidates
        if (target is None or item.target == target)
        and (subject is None or item.subject == subject)
        and (classification is None or item.classification == classification)
        and (text is None or item.evidence.text.casefold() == text.casefold())
    ]
    assert matches, (target, subject, classification, text, result.candidates)
    return matches[0]


def test_complex_english_message_preserves_roles_constraints_and_intent(dictionary, terminology):
    text = (
        "Design an elegant engagement ring with an oval sapphire in the center, two small round "
        "diamonds on the sides, a thin yellow-gold band, and no halo. "
        "Keep the overall look delicate."
    )
    result = parse_full_message(
        text,
        locale="en",
        dictionary=dictionary,
        knowledge_runtime=terminology,
    )

    assert result.original_text == text
    assert result.detected_language == MessageLanguage.EN
    assert result.knowledge_runtime_sha256 == terminology.sha256
    assert _find(result, target=StructuredTarget.JEWELRY_TYPE).parser_update is not None

    center_material = _find(
        result,
        target=StructuredTarget.CENTER_STONE_MATERIAL,
        subject=CandidateSubject.CENTER_STONE,
        text="sapphire",
    )
    assert center_material.normalized_values == ("stone.material.sapphire",)
    assert center_material.normalization_source == NormalizationSource.KNOWLEDGE_LIBRARY
    assert (
        _find(
            result,
            target=StructuredTarget.CENTER_STONE_SHAPE,
            subject=CandidateSubject.CENTER_STONE,
            text="oval",
        ).parser_update
        is not None
    )

    side_material = _find(
        result,
        target=StructuredTarget.SIDE_STONE_MATERIAL,
        subject=CandidateSubject.SIDE_STONES,
        text="diamonds",
    )
    assert side_material.parser_update is None
    assert side_material.application == CandidateApplication.STRUCTURED_EVIDENCE_ONLY
    assert _find(result, target=StructuredTarget.SIDE_STONE_SHAPE, text="round")
    assert _find(result, target=StructuredTarget.SIDE_STONE_QUANTITY).raw_value == {
        "value": 2,
        "scope": "per_item",
    }

    assert (
        _find(result, target=StructuredTarget.METAL_MATERIAL, text="gold").subject
        == CandidateSubject.BAND
    )
    assert (
        _find(result, target=StructuredTarget.METAL_COLOR, text="yellow").subject
        == CandidateSubject.BAND
    )
    prohibition = _find(result, classification=CandidateClassification.PROHIBITION, text="no halo")
    assert prohibition.parser_update is None
    assert set(prohibition.normalized_values) == {"halo_setting", "halo_style"}
    assert prohibition.semantic_subject == "feature.halo"
    delicate = _find(result, target=StructuredTarget.STYLE, text="delicate")
    assert delicate.certainty == CandidateCertainty.UNRESOLVED
    assert not any(
        item.target == StructuredTarget.CENTER_STONE_DIMENSIONS for item in result.candidates
    )


def test_complex_russian_message_has_equivalent_distinct_roles(dictionary, terminology):
    text = (
        "Хочу кольцо из жёлтого золота с овальным сапфиром в центре и двумя маленькими "
        "круглыми бриллиантами по бокам. Без гало. Дизайн должен быть лёгким и изящным."
    )
    result = parse_full_message(
        text,
        locale="ru",
        dictionary=dictionary,
        knowledge_runtime=terminology,
    )

    assert result.detected_language == MessageLanguage.RU
    assert _find(result, target=StructuredTarget.JEWELRY_TYPE, text="кольцо")
    assert _find(result, target=StructuredTarget.METAL_MATERIAL, text="золота")
    assert _find(result, target=StructuredTarget.METAL_COLOR, text="жёлтого")
    assert _find(result, target=StructuredTarget.CENTER_STONE_MATERIAL, text="сапфиром")
    assert _find(result, target=StructuredTarget.CENTER_STONE_SHAPE, text="овальным")
    assert _find(result, target=StructuredTarget.SIDE_STONE_MATERIAL, text="бриллиантами")
    assert _find(result, target=StructuredTarget.SIDE_STONE_SHAPE, text="круглыми")
    assert _find(result, target=StructuredTarget.SIDE_STONE_QUANTITY).raw_value["value"] == 2
    assert _find(result, classification=CandidateClassification.PROHIBITION, text="Без гало")
    assert _find(result, target=StructuredTarget.STYLE, text="лёгким")
    assert _find(result, target=StructuredTarget.STYLE, text="изящным")


def test_mixed_language_terms_are_detected_independently_of_session_locale(dictionary, terminology):
    result = parse_full_message(
        "Хочу кольцо with an oval sapphire в центре.",
        locale="ru",
        dictionary=dictionary,
        knowledge_runtime=terminology,
    )
    assert result.detected_language == MessageLanguage.MIXED
    assert _find(result, target=StructuredTarget.JEWELRY_TYPE, text="кольцо")
    assert _find(result, target=StructuredTarget.CENTER_STONE_SHAPE, text="oval")
    assert _find(result, target=StructuredTarget.CENTER_STONE_MATERIAL, text="sapphire")


def test_component_material_and_preservation_are_not_collapsed(dictionary, terminology):
    text = (
        "Make a platinum ring with an emerald-cut center diamond. Use yellow gold only for the "
        "prongs. No additional stones. Keep the center stone exactly as specified."
    )
    result = parse_full_message(
        text,
        locale="en",
        dictionary=dictionary,
        knowledge_runtime=terminology,
    )

    platinum = _find(result, target=StructuredTarget.METAL_MATERIAL, text="platinum")
    assert platinum.subject == CandidateSubject.PRODUCT_BODY
    assert platinum.parser_update is not None
    assert _find(result, target=StructuredTarget.CENTER_STONE_MATERIAL, text="diamond")
    assert _find(result, target=StructuredTarget.CENTER_STONE_SHAPE, text="emerald-cut")

    prong_gold = _find(result, target=StructuredTarget.METAL_MATERIAL, text="gold")
    assert prong_gold.subject == CandidateSubject.PRONGS
    assert prong_gold.parser_update is None
    assert "not represented" in prong_gold.detail
    assert (
        _find(result, target=StructuredTarget.METAL_COLOR, text="yellow").subject
        == CandidateSubject.PRONGS
    )
    assert _find(
        result, classification=CandidateClassification.PROHIBITION, text="No additional stones"
    )
    preserved = _find(
        result,
        classification=CandidateClassification.PRESERVATION,
        text="Keep the center stone exactly as specified",
    )
    assert preserved.subject == CandidateSubject.CENTER_STONE
    assert preserved.parser_update is None


def test_explicit_measurements_are_typed_without_dimension_inference(dictionary):
    text = "A ring with a 1.5 ct oval center diamond measuring 10 x 8 x 5 mm and two side diamonds."
    result = parse_full_message(text, locale="en", dictionary=dictionary)

    weight = _find(result, target=StructuredTarget.CENTER_STONE_WEIGHT)
    assert weight.parser_update.value.value.value == 1.5
    dimensions = _find(result, target=StructuredTarget.CENTER_STONE_DIMENSIONS)
    assert dimensions.parser_update.value.value.length.value == 10.0
    assert dimensions.parser_update.value.value.width.value == 8.0
    assert dimensions.parser_update.value.value.depth.value == 5.0
    assert _find(result, target=StructuredTarget.SIDE_STONE_QUANTITY).raw_value["value"] == 2

    no_dimensions = parse_full_message(
        "A ring with a 1.5 ct oval diamond.", locale="en", dictionary=dictionary
    )
    assert not any(
        item.target == StructuredTarget.CENTER_STONE_DIMENSIONS for item in no_dimensions.candidates
    )


def test_ambiguous_choices_and_unknown_words_remain_unresolved(dictionary):
    result = parse_full_message(
        "Perhaps an oval or emerald-cut center moonstone with aurora facets.",
        locale="en",
        dictionary=dictionary,
    )
    shapes = [
        item for item in result.candidates if item.target == StructuredTarget.CENTER_STONE_SHAPE
    ]
    assert len(shapes) == 2
    assert {item.certainty for item in shapes} == {CandidateCertainty.AMBIGUOUS}
    assert all(item.parser_update is None for item in shapes)
    unresolved = {
        item.evidence.text.casefold()
        for item in result.candidates
        if item.certainty == CandidateCertainty.UNRESOLVED
    }
    assert {"moonstone", "aurora", "facets"} <= unresolved


def test_evidence_offsets_are_exact_and_reject_tampering(dictionary):
    text = "A yellow-gold ring with an oval diamond."
    result = parse_full_message(text, locale="en", dictionary=dictionary)
    for candidate in result.candidates:
        span = candidate.evidence
        assert text[span.start : span.end] == span.text

    payload = result.model_dump(mode="json")
    payload["candidates"][0]["evidence"]["text"] = "tampered"
    with pytest.raises(ValidationError, match="does not match original input"):
        FullMessageParseResult.model_validate(payload)


def test_parsing_is_deterministic_and_does_not_mutate_product_state(dictionary, terminology):
    revision = DesignRevision.model_validate_json(
        (ROOT / "specs/jewelry-design-schema/fixtures/valid/ring.json").read_text()
    )
    before = revision.model_dump_json()
    text = "I prefer an oval sapphire center stone and a minimalist style."

    first = parse_full_message(
        text,
        locale="en",
        dictionary=dictionary,
        knowledge_runtime=terminology,
    )
    second = parse_full_message(
        text,
        locale="en",
        dictionary=dictionary,
        knowledge_runtime=terminology,
    )
    assert first == second
    assert revision.model_dump_json() == before
    assert all(
        item.classification == CandidateClassification.PREFERENCE
        for item in first.candidates
        if item.target
        in {
            StructuredTarget.CENTER_STONE_SHAPE,
            StructuredTarget.CENTER_STONE_MATERIAL,
            StructuredTarget.STYLE,
        }
    )
    assert "recommendation" not in json.dumps(first.model_dump(mode="json"))


def test_original_whitespace_and_wording_are_preserved(dictionary):
    text = "  I want a ring.\nKeep the original proportions.  "
    result = parse_full_message(text, locale="en", dictionary=dictionary)
    assert result.original_text == text
    preservation = _find(result, classification=CandidateClassification.PRESERVATION)
    assert preservation.evidence.text == "Keep the original proportions"


@pytest.mark.parametrize(
    ("text", "locale", "classification", "semantic_subject"),
    (
        ("Жёлтое золото, овальный сапфир, без гало.", "ru", "prohibition", "feature.halo"),
        ("Yellow gold ring, oval sapphire, без halo.", "ru", "prohibition", "feature.halo"),
        ("Create a platinum ring without engraving.", "en", "prohibition", "feature.engraving"),
        (
            "Change the center stone to round, but keep the original band.",
            "en",
            "preservation",
            "component.band",
        ),
        ("Actually, add a halo.", "en", "requirement", "feature.halo"),
    ),
)
def test_supported_non_schema_constraints_have_stable_semantic_subjects(
    dictionary, text, locale, classification, semantic_subject
):
    result = parse_full_message(text, locale=locale, dictionary=dictionary)

    candidate = next(
        item
        for item in result.candidates
        if item.classification.value == classification and item.semantic_subject == semantic_subject
    )
    assert candidate.certainty == CandidateCertainty.EXPLICIT
    assert candidate.application == CandidateApplication.STRUCTURED_EVIDENCE_ONLY
    assert candidate.parser_update is None


def test_unbound_preservation_remains_ambiguous_without_lock(dictionary):
    result = parse_full_message("Don't change that part.", locale="en", dictionary=dictionary)

    candidate = next(
        item
        for item in result.candidates
        if item.classification == CandidateClassification.PRESERVATION
    )
    assert candidate.certainty == CandidateCertainty.AMBIGUOUS
    assert candidate.semantic_subject is None
    assert candidate.parser_update is None


def test_empty_input_and_partial_knowledge_identity_fail_closed(dictionary):
    with pytest.raises(ValueError, match="non-whitespace"):
        parse_full_message("   ", locale="en", dictionary=dictionary)
    with pytest.raises(ValidationError, match="complete or absent"):
        FullMessageParseResult(
            original_text="ring",
            requested_locale="en",
            detected_language="en",
            dictionary_artifact_version="1.0.0",
            knowledge_package_id="partial",
        )
