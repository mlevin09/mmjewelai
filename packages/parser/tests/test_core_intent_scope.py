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
        ("An unwanted gold ring.", "gold"),
        ("An unnecessary platinum ring.", "platinum"),
        ("A gold ring doesn't suit me.", "gold"),
        ("A platinum ring does not appeal to me.", "platinum"),
        ("I wouldn't choose platinum.", "platinum"),
        ("Нежелательное золото. Кольцо.", "золото"),
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
        "Maybe, platinum. A ring.",
        "Я сомневаюсь, платина. Кольцо.",
        "Perhaps gold, platinum.",
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
        ("A gold ring doesn't have prongs.", "gold", "metal.material"),
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


@pytest.mark.parametrize(
    "text,positive,rejected,classification",
    (
        (
            "I want a gold ring and I do not want a platinum ring.",
            "gold",
            "platinum",
            "requirement",
        ),
        (
            "I do not want a platinum ring and I want a gold ring.",
            "gold",
            "platinum",
            "requirement",
        ),
        (
            "I want a gold ring and a platinum ring is not what I want.",
            "gold",
            "platinum",
            "requirement",
        ),
        ("Хочу золото и не хочу платину.", "золото", "платину", "preference"),
        ("Не хочу платину и хочу золото.", "золото", "платину", "preference"),
        ("I want a gold ring и не хочу платину.", "gold", "платину", "requirement"),
        ("No platinum and I want a gold ring.", "gold", "platinum", "requirement"),
        ("I reject platinum and want gold.", "gold", "platinum", "requirement"),
        ("I want gold and reject platinum.", "gold", "platinum", "requirement"),
        ("A gold ring, but a platinum ring is not what I want.", "gold", "platinum", "requirement"),
        ("I do not want platinum, I want a gold ring.", "gold", "platinum", "requirement"),
        ("I want gold\nI do not want platinum.", "gold", "platinum", "requirement"),
        ("I do not want platinum\nI want gold.", "gold", "platinum", "requirement"),
        ("I want gold and not platinum.", "gold", "platinum", "requirement"),
    ),
)
def test_independent_predicates_do_not_share_rejection(
    dictionary, text, positive, rejected, classification
):
    parsed = parse_full_message(text, locale="en", dictionary=dictionary)
    yes = next(c for c in parsed.candidates if c.evidence.text == positive)
    no = next(c for c in parsed.candidates if c.evidence.text == rejected)
    assert yes.classification == classification and yes.certainty == "explicit"
    assert yes.parser_update is not None
    assert no.classification == "prohibition" and no.parser_update is None
    assert parsed == parse_full_message(text, locale="en", dictionary=dictionary)


@pytest.mark.parametrize(
    "text",
    (
        "A gold ring and a platinum ring is not what I want.",
        "A gold ring and a platinum ring are unwanted.",
        "No gold and platinum.",
        "I do not want gold and platinum.",
    ),
)
def test_coordinated_objects_keep_their_shared_rejection(dictionary, text):
    metals = [
        c
        for c in parse_full_message(text, locale="en", dictionary=dictionary).candidates
        if c.target == "metal.material"
    ]
    assert len(metals) == 2
    assert all(c.classification == "prohibition" and c.parser_update is None for c in metals)


@pytest.mark.parametrize(
    "text,term,target,certainty",
    (
        ("Perhaps platinum and I want gold.", "gold", "metal.material", "explicit"),
        ("I want gold and perhaps platinum.", "gold", "metal.material", "explicit"),
        ("I want gold and perhaps platinum.", "platinum", "metal.material", "ambiguous"),
        ("No halo, engraving and gold.", "gold", "metal.material", "ambiguous"),
        (
            "No halo, white gold and I want an oval diamond center stone.",
            "gold",
            "metal.material",
            "ambiguous",
        ),
        (
            "No halo, white gold and I want an oval diamond center stone.",
            "diamond",
            "center_stone.material",
            "explicit",
        ),
        (
            "I want an oval diamond center stone and no gold prongs.",
            "diamond",
            "center_stone.material",
            "explicit",
        ),
        (
            "No side stones and I want an oval diamond center stone.",
            "oval",
            "center_stone.shape",
            "explicit",
        ),
    ),
)
def test_assertion_boundary_is_shared_by_certainty_and_ownership(
    dictionary, text, term, target, certainty
):
    parsed = parse_full_message(text, locale="en", dictionary=dictionary)
    candidate = next(c for c in parsed.candidates if c.evidence.text == term)
    assert candidate.target == target and candidate.certainty == certainty
    assert (candidate.parser_update is not None) == (certainty == "explicit")
    if certainty == "explicit":
        assert candidate.classification == "requirement"
    assert all(
        text[c.evidence.start : c.evidence.end] == c.evidence.text for c in parsed.candidates
    )
