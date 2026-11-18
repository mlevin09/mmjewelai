"""Authority intent precedes Library terminology binding; no provider calls."""

import json
from uuid import UUID

import pytest
from jewelai_parser.full_message import _parse_recorded_message
from test_conversation_model import context_inputs as context_inputs
from test_first_turn import EN, RU, get, post, setup
from test_professional_knowledge_http import real_client
from test_professional_knowledge_http import real_config as real_config

from jewelai_api.first_turn import creation_facts


@pytest.mark.parametrize(
    "locale,text",
    [
        ("en", "I would like to know about white gold earrings."),
        ("ru", "Хочу информацию о серьгах из белого золота."),
        ("en", "I want advice about white gold earrings."),
        ("ru", "Хочу серьги из белого золота обсудить."),
        ("ru", "Хочу серьги из белого золота изучить."),
        ("ru", "Хочу серьги из белого золота с двумя сапфирами обсудить."),
        ("en", "I want earrings made of white gold discussed."),
    ],
    ids=(
        "information-en",
        "information-ru",
        "advice-en",
        "postnominal-discuss",
        "postnominal-study",
        "nested-postnominal-discuss",
        "material-postnominal-discuss-en",
    ),
)
def test_information_intent_preserves_request_without_selecting_after_reload(
    engine, real_config, tmp_path, locale, text
):
    with real_client(engine, real_config) as (client, app, provider):
        sid, oid, body = setup(client, app, text, locale)
        service = app.state.prompt_enrichment_service
        repo = service.repository
        before = repo.get_current_revision(sid, oid)
        response = post(client, sid, oid, body)
        assert response.status_code == 201, response.json()
        after = repo.get_current_revision(sid, oid)
        receipt = response.json()
        bound = service._for_session(sid, oid)
        parsed = _parse_recorded_message(
            text,
            parse_version="1.3.0",
            locale=locale,
            dictionary=bound.artifacts.dictionary,
            knowledge_runtime=bound._load_release().compiled_runtime,
        )
        original = repo.get_message(sid, UUID(body["message_id"]), oid)
        cycle = repo.list_enrichment_cycles(sid, oid)[0]
        assert original.content == text
        assert provider.calls == []
    with real_client(engine, real_config) as (client, app, provider):
        restored = get(client, sid, oid)
        restored_revision = app.state.prompt_enrichment_service.repository.get_current_revision(
            sid, oid
        )
        # Preserve observable RED and GREEN receipts before asserting acceptance.
        (tmp_path / "first-turn-intent.json").write_text(
            json.dumps(
                dict(
                    input=text,
                    locale=locale,
                    request=body,
                    post_status=response.status_code,
                    response=receipt,
                    get_status=restored.status_code,
                    restored=restored.json(),
                    before=before.model_dump(mode="json"),
                    after=after.model_dump(mode="json"),
                    restored_revision=restored_revision.model_dump(mode="json"),
                    parse=parsed.model_dump(mode="json"),
                    matrix=cycle.result.model_dump(mode="json"),
                    provider_calls=0,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        assert restored.status_code == 200, restored.json()
        assert restored.json() == receipt
        assert after == before == restored_revision
        assert receipt["receipt"]["binding"]["selection_eligible"] is False
        assert receipt["receipt"]["binding"]["facts"] == []
        assert (
            "Новые параметры не приняты" if locale == "ru" else "No new parameters were accepted"
        ) in receipt["receipt"]["reply_text"]
        assert provider.calls == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I would like white gold earrings.", True),
        ("I want to create elegant white gold earrings.", True),
        ("Я хочу создать элегантные серьги из белого золота.", True),
        ("Please create a pair of white gold earrings.", True),
        ("I would like details about white gold earrings.", False),
        ("I want guidance on white gold earrings.", False),
        ("Хочу узнать больше о серьгах из белого золота.", False),
        ("Хочу совет о серьгах из белого золота.", False),
        ("I would like to know how to create white gold earrings.", False),
        ("Create a guide to white gold earrings.", False),
        ("I want white gold earrings explained.", False),
        ("Хочу серьги из белого золота, если возможно.", False),
    ],
)
def test_direct_creation_authority_is_source_backed_not_a_verb_blacklist(
    context_inputs, text, expected
):
    from jewelai_parser import parse_full_message

    parsed = parse_full_message(
        text,
        locale="ru" if "Хочу" in text or "Я хочу" in text else "en",
        dictionary=context_inputs["dictionary"],
        knowledge_runtime=context_inputs["active_runtime"].compiled_runtime,
    )
    # Every case must reach recognized jewelry vocabulary; refusal must be due
    # to authority intent, not an accidentally unrecognized product term.
    assert any("earrings" in c.normalized_values for c in parsed.candidates)
    before = parsed.model_dump_json()
    eligible, facts = creation_facts(parsed, context_inputs["active_runtime"].compiled_runtime)
    assert eligible is expected
    assert bool(facts) is expected
    assert parsed.model_dump_json() == before


@pytest.mark.parametrize("locale,text", [("ru", RU), ("en", EN)])
def test_approved_creation_still_commits_only_three_source_backed_values(
    engine, real_config, locale, text
):
    with real_client(engine, real_config) as (client, app, provider):
        sid, oid, body = setup(client, app, text, locale)
        response = post(client, sid, oid, body)
        assert response.status_code == 201, response.json()
        assert response.json()["receipt"]["binding"]["selection_eligible"] is True
        assert {
            f["target"]: f["value"] for f in response.json()["receipt"]["binding"]["facts"]
        } == {
            "jewelry_type": "earrings",
            "metal.material": "gold",
            "metal.color": "white",
        }
        design = app.state.prompt_enrichment_service.repository.get_current_revision(
            sid, oid
        ).design
        assert design.center_stone.material is None and design.side_stones == ()
        assert provider.calls == []


@pytest.mark.parametrize(
    "locale,text,expected",
    [
        ("ru", "Хочу серьги из белого золота, изучить.", False),
        ("ru", "Хочу серьги из белого золота и изучить.", False),
        ("ru", "Хочу серьги с двумя сапфирами изучить.", False),
        ("ru", "Хочу серьги из белого золота для сравнения.", False),
        ("en", "I would like earrings of white gold described.", False),
        ("en", "I want earrings with two sapphires studied.", False),
        ("en", "I want earrings made of white gold with two sapphires to be discussed.", False),
        ("ru", "Хочу серьги из white gold изучить.", False),
        ("en", "I want earrings with сапфирами обсудить.", False),
        ("en", "I want white gold earrings with.", False),
        ("ru", "Хочу серьги из.", False),
        ("en", "I want earrings made of white gold with two sapphires.", True),
        ("ru", "Хочу серьги из белого золота с тремя сапфирами.", True),
        ("en", "I want earrings with gold center stones.", True),
        ("ru", "Хочу серьги с золотыми центральными камнями.", True),
        ("ru", "Хочу серьги из белого золота сделать.", True),
        ("ru", "Хочу серьги из белого золота с двумя сапфирами создать.", True),
        ("en", "I want white gold earrings, and I do not want platinum.", True),
        ("ru", "Хочу серьги из золота и не хочу платину.", True),
        ("ru", "Хочу серьги из белого золота, с двумя сапфирами.", True),
    ],
)
def test_complete_creation_construction_has_no_uncovered_tail(
    context_inputs, locale, text, expected
):
    from jewelai_parser import parse_full_message

    parsed = parse_full_message(
        text,
        locale=locale,
        dictionary=context_inputs["dictionary"],
        knowledge_runtime=context_inputs["active_runtime"].compiled_runtime,
    )
    assert any("earrings" in c.normalized_values for c in parsed.candidates)
    before = parsed.model_dump_json()
    eligible, facts = creation_facts(parsed, context_inputs["active_runtime"].compiled_runtime)
    assert eligible is expected and bool(facts) is expected
    assert parsed.model_dump_json() == before
    if "gold center stones" in text or "золотыми центральными камнями" in text:
        assert {f.target: f.value for f in facts} == {"jewelry_type": "earrings"}
    if "do not want platinum" in text or "не хочу платину" in text:
        assert next(f.value for f in facts if f.target == "metal.material") == "gold"
    assert all(f.target in {"jewelry_type", "metal.material", "metal.color"} for f in facts)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Хочу серьги из белого золота, не покупать, а изучить.", False),
        ("I want earrings of white gold, not to buy but to study.", False),
        ("Хочу серьги из золота, но не из платины.", True),
        ("I want gold earrings without side stones.", True),
    ],
)
def test_negated_tail_must_be_a_complete_nominal_not_a_skipped_action(
    context_inputs, text, expected
):
    from jewelai_parser import parse_full_message

    parsed = parse_full_message(
        text,
        locale="ru" if text.startswith("Хочу") else "en",
        dictionary=context_inputs["dictionary"],
        knowledge_runtime=context_inputs["active_runtime"].compiled_runtime,
    )
    assert any("earrings" in c.normalized_values for c in parsed.candidates)
    eligible, facts = creation_facts(parsed, context_inputs["active_runtime"].compiled_runtime)
    assert eligible is expected and bool(facts) is expected
    if expected:
        assert {f.target: f.value for f in facts} == {
            "jewelry_type": "earrings",
            "metal.material": "gold",
        }
