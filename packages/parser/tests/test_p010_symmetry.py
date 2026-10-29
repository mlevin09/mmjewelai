import json
from pathlib import Path

import pytest
from jewelai_domain import load_domain_dictionary
from jewelai_domain.knowledge_library_v1_1 import compile_knowledge_library_v1_1

from jewelai_parser import parse_full_message
from jewelai_parser.p010_symmetry import TARGET, has_p010_binding

ROOT = Path(__file__).resolve().parents[3]
SLICE = ROOT / "data/knowledge/v1_1/p010-symmetry-0.1.0.json"
ORIGINAL = "Асимметричное кольцо — не выравнивай его."
REVIEW_NEGATIVES = (
    "Асимметричное кольцо не нужно.",
    "Не хочу, чтобы было асимметричное кольцо.",
    "An asymmetric ring is not what I want.",
    "Я сомневаюсь, нужно ли асимметричное кольцо.",
    "An asymmetric design for the website.",
    "An asymmetric composition for the photograph.",
)
SCOPE_REVIEW_CASES = (
    ("Асимметричное кольцо\nне нужно.", False, False, False),
    ("An asymmetric ring\nis not what I want.", False, False, False),
    ("An asymmetric ring\nphotograph.", False, False, False),
    ("An asymmetric jewelry\nwebsite design.", False, False, False),
    ("An asymmetric ring. Maybe,\ndo not make it symmetrical.", True, False, False),
    ("An asymmetric ring. I don't mean,\ndo not make it symmetrical.", True, False, False),
    ("An asymmetric ring, no halo.", True, False, True),
    ("An asymmetric ring without a halo.", True, False, True),
    ("Асимметричное кольцо без гало.", True, False, True),
)


SCOPE_CONTROLS = (
    ("Асимметричное кольцо — не выравнивай его.", True, True, False),
    ("An asymmetric ring, no halo. Do not make it symmetrical.", True, True, True),
    ("An asymmetric ring.\nNo halo.", True, False, True),
    ("No halo. An asymmetric ring.", True, False, True),
    ("An asymmetrical jewelry design.", True, False, False),
    ("Не хочу,\nчтобы было асимметричное кольцо.", False, False, False),
    ("An asymmetric ring\nis unnecessary.", False, False, False),
    ("An asymmetric ring.\nMaybe, do not make it symmetrical.", True, False, False),
    ("Асимметричное кольцо\nбез гало — не выравнивай его.", True, True, True),
    ("An asymmetric ring, no halo — do not\nmake it symmetrical.", True, True, True),
    ("No asymmetric ring without a halo.", False, False, True),
    ("No halo or an asymmetric ring.", False, False, True),
    ("An asymmetric ring, do not add a halo — do not make it symmetrical.", True, True, True),
    ("An asymmetric ring, without engraving.", True, False, False),
    ("No halo;\nAn asymmetric ring.", True, False, True),
    # With no explicit statement boundary, a shared negative list is ambiguous.
    ("No halo\nAn asymmetric ring.", False, False, True),
    ("An asymmetric ring, no halo or asymmetry.", False, False, True),
    ("An asymmetric ring, no halo or side stones.", False, False, True),
)


@pytest.mark.parametrize("text,symmetry,keep,halo", SCOPE_REVIEW_CASES + SCOPE_CONTROLS)
def test_review_semantic_scope(text, symmetry, keep, halo):
    parsed = parse(text)
    assert parsed.original_text == text
    assert (
        any(
            c.semantic_subject == TARGET
            and c.classification == "requirement"
            and c.certainty == "explicit"
            for c in parsed.candidates
        )
        is symmetry
    )
    assert (
        any(
            c.semantic_subject == TARGET and c.classification == "preservation"
            for c in parsed.candidates
        )
        is keep
    )
    if halo:
        assert any(
            c.semantic_subject == "feature.halo" and c.classification == "prohibition"
            for c in parsed.candidates
        )
    for candidate in parsed.candidates:
        span = candidate.evidence
        assert text[span.start : span.end] == span.text


@pytest.mark.parametrize("text", REVIEW_NEGATIVES)
def test_review_false_positives_never_assert_symmetry(text):
    parsed = parse(text)
    assert parsed.original_text == text
    assert not any(
        c.semantic_subject == TARGET
        and c.classification == "requirement"
        and c.certainty == "explicit"
        for c in parsed.candidates
    )
    assert not any(
        c.semantic_subject == TARGET and c.classification == "preservation"
        for c in parsed.candidates
    )


def parse(text, payload=None):
    runtime = compile_knowledge_library_v1_1(
        json.loads(SLICE.read_text()) if payload is None else payload
    )[0]
    return parse_full_message(
        text,
        locale="ru" if any("а" <= char.casefold() <= "я" for char in text) else "en",
        dictionary=load_domain_dictionary(ROOT / "data/dictionary/v1.0.0.json"),
        knowledge_runtime=runtime,
    )


@pytest.mark.parametrize(
    "text",
    [
        ORIGINAL,
        "An asymmetric ring.",
        "An asymmetrical ring.",
        "An asymmetrical jewelry design.",
        "The jewelry design is asymmetric.",
        "Асимметричное ювелирное украшение.",
        "An asymmetric ring. Do not make it symmetrical.",
        "Асимметричное кольцо, не выравнивай его.",
        "An asymmetric ring, do not make it symmetrical.",
        "No halo. An asymmetric ring.",
        "An asymmetric ring. No halo.",
    ],
)
def test_p010_explicit_user_evidence_uses_real_knowledge(text):
    parsed = parse(text)
    candidate = next(c for c in parsed.candidates if c.semantic_subject == TARGET)
    assert candidate.classification == "requirement"
    assert candidate.certainty == "explicit"
    assert candidate.normalization_source == "knowledge_library"
    assert candidate.normalized_values == ("asymmetry",)
    assert candidate.target is None and candidate.parser_update is None
    assert "LANG-P010-C2-" in candidate.detail and "/mini_tests/9" in candidate.detail
    assert parsed.original_text == text
    if text == ORIGINAL:
        keep = next(c for c in parsed.candidates if c.classification == "preservation")
        assert keep.semantic_subject == TARGET and keep.evidence.text == "не выравнивай его"
    elif "Do not" in text:
        keep = next(c for c in parsed.candidates if c.classification == "preservation")
        assert keep.semantic_subject == TARGET
        assert keep.evidence.text == "Do not make it symmetrical"


@pytest.mark.parametrize(
    "text",
    [
        "An Art Deco ring.",
        "An organic ring.",
        "A geometric ring.",
        "A symmetrical ring.",
        "An asymmetric stone in a ring.",
        "An asymmetric face.",
        "Asymmetry in photography.",
        "No asymmetric ring.",
        "Not an asymmetrical ring.",
        "I reject an asymmetric ring.",
        "Maybe an asymmetric ring.",
        "Would you recommend an asymmetric ring?",
        "An asymmetric ring, but make the ring symmetrical.",
        "Не хочу асимметричное кольцо.",
        "If I wanted an asymmetric ring.",
        "The term asymmetric ring is in the glossary.",
        "An asymmetric ring-shaped box.",
        "The earring is asymmetric.",
        "An asymmetric ring. No asymmetric ring.",
        "An asymmetric ring isn't wanted.",
        "I do not want, despite appearances, an asymmetric ring.",
        "Асимметричное кольцо, но оно не нужно.",
        "An asymmetric ring is not what I want — do not make it symmetrical.",
        "Я не уверен, что нужно асимметричное кольцо.",
        "Нужно ли асимметричное кольцо?",
        "I am unsure whether an asymmetric ring is needed.",
        "An asymmetric ring?",
        "Асимметричное украшение для сайта.",
        "Асимметричное композиция для фотографии.",
        "An asymmetric website design with a ring.",
        "An asymmetric design. Do not make it symmetrical.",
        "An asymmetric ring is unnecessary.",
        "Асимметричное кольцо нежелательно.",
        "An asymmetric jewelry website design.",
        "An asymmetric ring photograph.",
    ],
)
def test_p010_does_not_turn_negation_uncertainty_or_style_into_a_fact(text):
    parsed = parse(text)
    assert not any(
        c.semantic_subject == TARGET
        and c.classification == "requirement"
        and c.certainty == "explicit"
        for c in parsed.candidates
    )


def test_t10_12_bounded_observation_is_not_full_acceptance():
    parsed = parse("Art Deco, organic and asymmetric.")
    # No explicit product referent: preserve the original message as deferred
    # evidence, rather than treating a style list as a canonical symmetry fact.
    assert parsed.original_text == "Art Deco, organic and asymmetric."
    assert not any(c.semantic_subject == TARGET for c in parsed.candidates)
    assert not any(c.classification == "preservation" for c in parsed.candidates)
    assert not any(c.parser_update for c in parsed.candidates)


def test_p010_binding_requires_approved_record_graph_not_a_concept_name():
    payload = json.loads(SLICE.read_text())
    payload["policies"] = []
    runtime = compile_knowledge_library_v1_1(payload)[0]
    assert not has_p010_binding(runtime)
    assert not any(c.semantic_subject == TARGET for c in parse(ORIGINAL, payload).candidates)


def test_future_library_alias_does_not_expand_the_approved_binding():
    payload = json.loads(SLICE.read_text())
    payload["language_mappings"][1]["aliases"].append("unbalanced")
    assert not any(
        c.semantic_subject == TARGET for c in parse("An unbalanced ring.", payload).candidates
    )


@pytest.mark.parametrize(
    "continuation",
    [
        "I don't mean, do not make it symmetrical.",
        "Maybe, do not make it symmetrical.",
        "Do not make it symmetrical?",
        "For the website, do not make it symmetrical.",
    ],
)
def test_governed_or_questioned_preservation_is_not_exempted(continuation):
    parsed = parse(f"An asymmetric ring. {continuation}")
    assert any(
        c.semantic_subject == TARGET
        and c.classification == "requirement"
        and c.certainty == "explicit"
        for c in parsed.candidates
    )
    assert not any(
        c.semantic_subject == TARGET and c.classification == "preservation"
        for c in parsed.candidates
    )
