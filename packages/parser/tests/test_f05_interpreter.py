"""Parser1.2 recognition cannot silently change retained parser1.1 evidence."""

from pathlib import Path

import pytest
from jewelai_domain import load_domain_dictionary

from jewelai_parser.full_message import parse_full_message as legacy_parse
from jewelai_parser.full_message_v1_2 import parse_full_message


@pytest.fixture(scope="module")
def dictionary():
    return load_domain_dictionary(
        Path(__file__).resolve().parents[3] / "data/dictionary/v1.0.0.json"
    )


@pytest.mark.parametrize(
    "text,locale",
    [
        ("Сохранить центральный камень без изменений.", "ru"),
        ("Keep the center-stone shape unchanged.", "en"),
        ("A gold ring. Сохранить центральный камень без изменений.", "ru"),
    ],
)
def test_new_preservation_grammar_has_a_distinct_interpreter(dictionary, text, locale):
    old = legacy_parse(text, locale=locale, dictionary=dictionary)
    saved = old.model_dump_json()
    new = parse_full_message(text, locale=locale, dictionary=dictionary)
    assert new.parse_version == "1.2.0"
    assert any(c.classification == "preservation" for c in new.candidates)
    assert legacy_parse(text, locale=locale, dictionary=dictionary).model_dump_json() == saved
    assert old.parse_version == "1.1.0"
    for candidate in new.candidates:
        assert text[candidate.evidence.start : candidate.evidence.end] == candidate.evidence.text


def test_independent_positive_fact_survives_new_preservation_grammar(dictionary):
    parsed = parse_full_message(
        "A gold ring. Сохранить центральный камень без изменений.",
        locale="ru",
        dictionary=dictionary,
    )
    assert any(
        c.target == "metal.material" and c.classification == "requirement"
        for c in parsed.candidates
    )
