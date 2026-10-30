"""Intent and ownership must not depend on an optional Knowledge binding."""

from pathlib import Path

import pytest
from jewelai_domain import load_domain_dictionary

from jewelai_parser import parse_full_message

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def dictionary():
    return load_domain_dictionary(ROOT / "data/dictionary/v1.0.0.json")


@pytest.mark.parametrize(
    "text,term",
    (
        ("A gold ring is not what I want.", "gold"),
        ("The platinum ring is unwanted.", "platinum"),
        ("Кольцо из золота мне не подходит.", "золота"),
        ("Кольцо из платины не нужно.", "платины"),
        ("I reject gold.", "gold"),
    ),
)
def test_governed_rejection_is_not_a_positive_candidate(dictionary, text, term):
    parsed = parse_full_message(text, locale="en", dictionary=dictionary)
    candidates = [c for c in parsed.candidates if c.evidence.text == term]
    assert candidates
    assert all(c.classification == "prohibition" and c.parser_update is None for c in candidates)


@pytest.mark.parametrize(
    "text",
    (
        "Maybe platinum. A ring.",
        "Perhaps platinum. A ring.",
        "Возможно платина. Кольцо.",
        "A platinum ring, perhaps.",
    ),
)
def test_tentative_single_value_is_not_explicit_authority(dictionary, text):
    parsed = parse_full_message(text, locale="en", dictionary=dictionary)
    candidates = [c for c in parsed.candidates if c.target == "metal.material"]
    assert candidates and all(c.certainty != "explicit" for c in candidates)
    assert all(c.parser_update is None for c in candidates)


@pytest.mark.parametrize(
    "text,term,target",
    (
        ("An oval diamond ring. No side stones.", "oval", "center_stone.shape"),
        ("No side stones. An oval diamond ring.", "diamond", "center_stone.material"),
        ("An oval diamond ring without side stones.", "oval", "center_stone.shape"),
        ("A gold ring. No prongs.", "gold", "metal.material"),
        ("A gold ring without prongs.", "gold", "metal.material"),
        ("Кольцо из золота. Крапаны не нужны.", "золота", "metal.material"),
        (
            "An oval diamond center stone. Боковые камни не нужны.",
            "diamond",
            "center_stone.material",
        ),
    ),
)
def test_independent_rejection_cannot_steal_component_owner(dictionary, text, term, target):
    parsed = parse_full_message(text, locale="en", dictionary=dictionary)
    candidates = [c for c in parsed.candidates if c.evidence.text == term]
    assert candidates
    assert all(c.target == target and c.parser_update is not None for c in candidates)
    assert all(c.classification == "requirement" for c in candidates)


@pytest.mark.parametrize(
    "text",
    (
        "A ring, no halo, yellow gold or oval diamond.",
        "A ring, no diamond, yellow gold.",
        "A ring, no mysterious object, white gold.",
        "Кольцо, без гало, белое золото или овальный алмаз.",
    ),
)
def test_unclosed_negative_list_never_leaks_dictionary_updates(dictionary, text):
    parsed = parse_full_message(text, locale="en", dictionary=dictionary)
    values = [c for c in parsed.candidates if c.target not in {None, "jewelry_type"}]
    assert values and all(c.parser_update is None for c in values)


@pytest.mark.parametrize(
    "text",
    (
        "A gold ring. No prongs.",
        "No prongs. A gold ring.",
        "I do not want platinum. A gold ring.",
        "A gold ring. Perhaps platinum.",
    ),
)
def test_independent_positive_gold_survives(dictionary, text):
    parsed = parse_full_message(text, locale="en", dictionary=dictionary)
    gold = [c for c in parsed.candidates if c.evidence.text == "gold"]
    assert gold and all(c.parser_update is not None for c in gold)
    assert parsed == parse_full_message(text, locale="en", dictionary=dictionary)
    assert all(
        text[c.evidence.start : c.evidence.end] == c.evidence.text for c in parsed.candidates
    )


@pytest.mark.parametrize(
    "text",
    (
        "No platinum, but a gold ring.",
        "Без платины, но кольцо из золота.",
        "A gold ring, but no prongs.",
    ),
)
def test_contrast_separates_independent_assertions(dictionary, text):
    parsed = parse_full_message(text, locale="en", dictionary=dictionary)
    gold = [c for c in parsed.candidates if c.normalized_values == ("gold",)]
    assert gold and all(c.parser_update is not None for c in gold)


@pytest.mark.parametrize(
    "text",
    (
        "Maybe add a halo.",
        "Perhaps no side stones.",
        "Возможно add a halo.",
    ),
)
def test_uncertain_special_instructions_are_not_explicit(dictionary, text):
    parsed = parse_full_message(text, locale="en", dictionary=dictionary)
    constraints = [c for c in parsed.candidates if c.semantic_subject is not None]
    assert constraints and all(c.certainty == "ambiguous" for c in constraints)


def test_uncertain_rejection_is_not_misrepresented_as_prohibition(dictionary):
    parsed = parse_full_message("Not sure about gold.", locale="en", dictionary=dictionary)
    gold = next(c for c in parsed.candidates if c.evidence.text == "gold")
    assert gold.certainty == "ambiguous" and gold.classification != "prohibition"
    assert gold.parser_update is None


def test_decimal_point_is_not_an_alternative_statement_boundary(dictionary):
    parsed = parse_full_message("Gold ring 1.0 mm or platinum.", locale="en", dictionary=dictionary)
    metals = [c for c in parsed.candidates if c.target == "metal.material"]
    assert len(metals) == 2 and all(c.certainty == "ambiguous" for c in metals)
    assert all(c.parser_update is None for c in metals)
