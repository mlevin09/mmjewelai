"""F01: linguistic ownership is separate from canonical binding authority."""

import json
from pathlib import Path

import pytest
from jewelai_domain import load_domain_dictionary
from jewelai_domain.knowledge_library_v1_1 import compile_knowledge_library_v1_1

from jewelai_parser import parse_full_message

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(
    scope="module", params=(False, True), ids=("dictionary-only", "existing-core-knowledge")
)
def context(request):
    dictionary = load_domain_dictionary(ROOT / "data/dictionary/v1.0.0.json")
    payload = json.loads((ROOT / "data/knowledge/v1/jewelry-core-1.0.0.json").read_text())
    payload["contract_version"] = "1.1.0"
    runtime = compile_knowledge_library_v1_1(payload)[0] if request.param else None
    return dictionary, runtime


@pytest.mark.parametrize(
    "text,term,owner,target,eligible",
    (
        ("A platinum ring with gold prongs.", "platinum", "product_body", "metal.material", True),
        ("A gold ring with a platinum shank.", "gold", "product_body", "metal.material", True),
        ("A gold ring with a platinum head.", "gold", "product_body", "metal.material", True),
        ("Platinum shank with rose-gold prongs.", "Platinum", "band", None, False),
        ("Platinum shank with rose-gold prongs.", "rose", "prongs", None, False),
        ("Platinum shank with rose-gold prongs.", "gold", "prongs", None, False),
        ("A gold ring with a platinum head.", "platinum", "unknown", None, False),
        ("A platinum ring with a gold setting.", "gold", "setting", None, False),
        ("A gold setting.", "gold", "setting", None, False),
        ("A platinum ring with gold coating.", "gold", "unknown", None, False),
        ("A gold-plated platinum ring.", "gold", "unknown", None, False),
        ("A gold ring with a platinum split-shank.", "platinum", "band", None, False),
        ("A platinum split-shank.", "platinum", "band", None, False),
        (
            "A matte platinum split-shank ring with an east-west blue sapphire.",
            "platinum",
            "product_body",
            "metal.material",
            True,
        ),
        (
            "Oval emerald side stones with a diamond center stone.",
            "emerald",
            "side_stones",
            "side_stones.{group_id}.stones.material",
            False,
        ),
        (
            "Oval emerald side stones with a diamond center stone.",
            "diamond",
            "center_stone",
            "center_stone.material",
            True,
        ),
        ("Gold prongs with a platinum ring.", "platinum", "product_body", "metal.material", True),
        ("Кольцо из золота с платиновой шинкой.", "золота", "product_body", "metal.material", True),
        ("Платиновая шинка с розовым золотом в крапанах.", "розовым", "prongs", None, False),
        (
            "Овальные изумруды по бокам, алмаз в центре.",
            "изумруды",
            "side_stones",
            "side_stones.{group_id}.stones.material",
            False,
        ),
    ),
)
def test_owner_and_application(context, text, term, owner, target, eligible):
    dictionary, runtime = context
    result = parse_full_message(text, locale="ru", dictionary=dictionary, knowledge_runtime=runtime)
    candidates = [
        c
        for c in result.candidates
        if (
            c.evidence.text == term
            or (term in {"rose", "розовым"} and c.normalized_values == ("rose",))
        )
        and c.normalization_source == "domain_dictionary"
    ]
    assert candidates, term
    candidate = candidates[0]
    assert candidate.subject == owner, candidate
    assert candidate.target == target, candidate
    assert (candidate.parser_update is not None) is eligible
    assert all(
        text[c.evidence.start : c.evidence.end] == c.evidence.text for c in result.candidates
    )
    assert result == parse_full_message(
        text, locale="ru", dictionary=dictionary, knowledge_runtime=runtime
    )


@pytest.mark.parametrize(
    "text,term,owner",
    (
        (
            "A matte platinum split-shank ring with an east-west blue sapphire.",
            "blue",
            "center_stone",
        ),
        ("A gold ring with round sapphire side stones.", "round", "side_stones"),
        ("A gold ring with round sapphire side stones.", "sapphire", "side_stones"),
    ),
)
def test_unrepresented_words_keep_their_owner(context, text, term, owner):
    dictionary, runtime = context
    result = parse_full_message(text, locale="en", dictionary=dictionary, knowledge_runtime=runtime)
    candidate = next(c for c in result.candidates if c.evidence.text == term)
    assert candidate.subject == owner
    assert candidate.parser_update is None


@pytest.mark.parametrize(
    "text", ("Platinum shank with rose-gold prongs.", "A platinum head.", "A gold band.")
)
def test_component_mentions_never_offer_global_updates(context, text):
    dictionary, runtime = context
    result = parse_full_message(text, locale="en", dictionary=dictionary, knowledge_runtime=runtime)
    assert not any(c.parser_update for c in result.candidates), result


@pytest.mark.parametrize(
    "text",
    (
        "No 3 ct center stone. A gold ring.",
        "Maybe a 7 x 5 x 3 mm center stone.",
        "A shank 7 x 5 x 3 mm.",
    ),
)
def test_measurement_authority_and_component_scope(context, text):
    dictionary, runtime = context
    result = parse_full_message(text, locale="en", dictionary=dictionary, knowledge_runtime=runtime)
    measurements = [
        c for c in result.candidates if c.normalization_source == "deterministic_pattern"
    ]
    assert measurements
    assert all(c.parser_update is None for c in measurements)


def test_independent_setting_not_stolen_by_other_component_metal(context):
    dictionary, runtime = context
    result = parse_full_message(
        "Gold prongs. An oval diamond center stone in prongs.",
        locale="en",
        dictionary=dictionary,
        knowledge_runtime=runtime,
    )
    settings = [
        c
        for c in result.candidates
        if c.evidence.text == "prongs" and c.normalization_source == "domain_dictionary"
    ]
    assert len(settings) == 2
    assert settings[0].parser_update is None
    assert settings[1].target == "center_stone.setting" and settings[1].parser_update is not None


@pytest.mark.parametrize(
    "text,owner,classification",
    (
        ("Delicate prongs on a gold ring.", "prongs", "preference"),
        ("No delicate prongs.", "prongs", "prohibition"),
        ("A delicate gold ring.", "overall_design", "preference"),
        ("Не нужны изящные крапаны.", "prongs", "prohibition"),
    ),
)
def test_unreviewed_aesthetic_is_owned_but_not_accepted(context, text, owner, classification):
    dictionary, runtime = context
    parsed = parse_full_message(text, locale="ru", dictionary=dictionary, knowledge_runtime=runtime)
    candidate = next(
        c
        for c in parsed.candidates
        if c.normalization_source == "none"
        and c.evidence.text.casefold() in {"delicate", "изящные"}
    )
    assert candidate.subject == owner and candidate.classification == classification
    assert candidate.parser_update is None and candidate.certainty == "unresolved"
