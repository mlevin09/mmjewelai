"""One current extraction algorithm with retained immutable wire formats."""

from pathlib import Path

import pytest
from jewelai_domain import load_domain_dictionary

from jewelai_parser.full_message import (
    FullMessageParseResult,
    FullMessageParseResultV1_2,
    parse_full_message,
    read_full_message_parse_result,
    same_parse_evidence,
)


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
def test_wire_formats_use_identical_current_extraction(dictionary, text, locale):
    new = parse_full_message(text, locale=locale, dictionary=dictionary)
    assert type(new) is FullMessageParseResultV1_2
    assert new.parse_version == "1.2.0"
    assert any(c.classification == "preservation" for c in new.candidates)
    # Frozen historical evidence is a data fixture, not another parsing operation.
    old = FullMessageParseResult(**new.model_dump(exclude={"parse_version"}))
    saved = old.model_dump_json()
    assert same_parse_evidence(old, new)
    assert read_full_message_parse_result(old.model_dump(mode="json")).model_dump_json() == saved
    assert parse_full_message(text, locale=locale, dictionary=dictionary) == new
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


@pytest.mark.parametrize("version", [None, "1.0.0", "1.3.0"])
def test_evidence_reader_requires_an_explicit_supported_version(dictionary, version):
    payload = parse_full_message("A gold ring.", locale="en", dictionary=dictionary).model_dump(
        mode="json"
    )
    if version is None:
        del payload["parse_version"]
    else:
        payload["parse_version"] = version
    with pytest.raises(ValueError):
        read_full_message_parse_result(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("original_text", "A gold ring. Extra text."),
        ("requested_locale", "ru"),
        ("dictionary_artifact_version", "9.9.9"),
        ("candidates", []),
    ],
)
def test_wire_comparison_never_ignores_other_evidence(dictionary, field, value):
    current = parse_full_message("A gold ring.", locale="en", dictionary=dictionary)
    historical = current.model_dump(mode="json")
    historical["parse_version"] = "1.1.0"
    assert same_parse_evidence(historical, current)
    historical[field] = value
    assert not same_parse_evidence(historical, current)


def test_new_parse_cannot_select_historical_wire_format(dictionary):
    with pytest.raises(TypeError, match="_result_type"):
        parse_full_message(
            "A gold ring.", locale="en", dictionary=dictionary, _result_type=FullMessageParseResult
        )


@pytest.mark.parametrize(
    "text,locale",
    [
        ("Maybe keep the center stone shape unchanged.", "en"),
        ("Probably keep the center stone shape unchanged.", "en"),
        ("Наверное сохранить центральный камень без изменений.", "ru"),
        ("Вероятно сохранить центральный камень без изменений.", "ru"),
        ("Необязательно сохранить центральный камень без изменений.", "ru"),
        ("Незачем сохранить центральный камень без изменений.", "ru"),
        ("I refuse to keep the center stone shape unchanged.", "en"),
        ("Keep the center stone unchanged, probably.", "en"),
        ("Сохранить центральный камень без изменений необязательно.", "ru"),
        ("Do you think we should keep the center stone shape unchanged?", "en"),
        ("Нужно ли сохранить центральный камень без изменений?", "ru"),
        ("Do not keep the center stone material and keep the center stone shape unchanged.", "en"),
        ("Возможно сохранить центральный камень без изменений.", "ru"),
        ("Не нужно сохранить центральный камень без изменений.", "ru"),
        ("Maybe preserve the center stone shape unchanged. A platinum ring.", "en"),
        ("Either keep the center stone shape unchanged or change it.", "en"),
        ("Сохранить центральный камень без изменений или изменить его.", "ru"),
        ("Do not preserve the center stone shape unchanged.", "en"),
        ("A gold ring. Perhaps preserve the center stone shape unchanged.", "en"),
    ],
)
def test_preservation_authority_requires_affirmative_certain_assertion(dictionary, text, locale):
    parsed = parse_full_message(text, locale=locale, dictionary=dictionary)
    assert not any(
        c.classification == "preservation" and c.certainty == "explicit" for c in parsed.candidates
    )
    assert parsed.candidates  # unresolved/rejected evidence is retained
    for c in parsed.candidates:
        assert text[c.evidence.start : c.evidence.end] == c.evidence.text
    if "platinum" in text:
        assert any(
            c.target == "metal.material" and c.classification == "requirement"
            for c in parsed.candidates
        )


@pytest.mark.parametrize(
    "text,locale",
    [
        ("Do not change the center stone shape.", "en"),
        ("I do not want a halo and keep the center stone shape unchanged.", "en"),
        ("Не хочу гало и сохранить центральный камень без изменений.", "ru"),
        ("Maybe a gold ring\nKeep the center stone shape unchanged.", "en"),
        ("Не менять центральный камень.", "ru"),
        ("Хочу сохранить центральный камень без изменений.", "ru"),
        ("I would like to keep the center stone shape unchanged.", "en"),
        ("Maybe a gold ring. Keep the center stone shape unchanged.", "en"),
        ("Do not add side stones, but keep the center stone shape unchanged.", "en"),
    ],
)
def test_preservation_idiom_and_independent_affirmation_keep_authority(dictionary, text, locale):
    parsed = parse_full_message(text, locale=locale, dictionary=dictionary)
    assert any(
        c.classification == "preservation" and c.certainty == "explicit" for c in parsed.candidates
    )


@pytest.mark.parametrize(
    "text,expected,certainty",
    [
        ("Овальный центральный алмаз в крапановой закрепке.", "center_stone", "explicit"),
        ("Возможно овальный центральный алмаз в крапановой закрепке.", "center_stone", "ambiguous"),
        ("Не хочу центральный алмаз в крапановой закрепке.", "center_stone", "explicit"),
        ("Oval центральный алмаз в крапановой закрепке.", "center_stone", "explicit"),
        ("Боковые алмазы в крапановой закрепке.", "side_stones", "explicit"),
    ],
)
def test_explicit_owner_precedes_neighboring_setting(dictionary, text, expected, certainty):
    parsed = parse_full_message(text, locale="ru", dictionary=dictionary)
    stones = [c for c in parsed.candidates if c.normalized_values == ("diamond",)]
    assert stones
    assert all(c.subject == expected and c.certainty == certainty for c in stones)
    if "Не хочу" in text:
        assert all(c.classification == "prohibition" and c.parser_update is None for c in stones)
    if expected in {"side_stones", "unknown"}:
        assert all(c.parser_update is None for c in stones)


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "Keep the center stone exactly as specified. Do not change its dimensions. "
            "Use a refined, minimalist appearance.",
            ("Keep the center stone exactly as specified",),
        ),
        (
            "Preserve the center stone exactly as specified.",
            ("Preserve the center stone exactly as specified",),
        ),
        ("Do not change the center stone shape.", ("Do not change the center stone shape",)),
        ("Keep the center-stone shape unchanged.", ("Keep the center-stone shape unchanged",)),
        (
            "Сохранить центральный камень без изменений.",
            ("Сохранить центральный камень без изменений",),
        ),
        (
            "Keep the center stone exactly as specified. Preserve the band.",
            ("Keep the center stone exactly as specified", "Preserve the band"),
        ),
        (
            "Keep the center stone. Preserve the original center stone.",
            ("Keep the center stone", "Preserve the original center stone"),
        ),
    ],
)
def test_preservation_recognizers_keep_enclosing_occurrence_not_its_prefix(
    dictionary, text, expected
):
    result = parse_full_message(
        text, locale="ru" if text.startswith("Сохранить") else "en", dictionary=dictionary
    )
    keeps = [c for c in result.candidates if c.classification == "preservation"]
    assert tuple(c.evidence.text for c in keeps) == expected
    assert all(c.certainty == "explicit" and c.parser_update is None for c in keeps)
    assert all(text[c.evidence.start : c.evidence.end] == c.evidence.text for c in keeps)
    assert len({c.candidate_id for c in result.candidates}) == len(result.candidates)
    if text == "Keep the center stone. Preserve the original center stone.":
        assert keeps[0].detail == "Sourced preservation is not a canonical value update."


@pytest.mark.parametrize("prefix", ["Maybe ", "I refuse to ", "Probably "])
def test_longer_preservation_match_still_requires_affirmative_authority(dictionary, prefix):
    result = parse_full_message(
        prefix + "keep the center stone exactly as specified.", locale="en", dictionary=dictionary
    )
    keeps = [c for c in result.candidates if c.classification == "preservation"]
    assert len(keeps) == 1 and keeps[0].certainty != "explicit"
    assert keeps[0].parser_update is None
