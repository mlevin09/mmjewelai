"""Actual persisted opt-in HTTP, pinned real catalog and legacy-reader controls."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from conftest import create_hierarchy
from jewelai_domain.clarification_state import evidence_hash
from jewelai_persistence import create_session_factory
from jewelai_persistence.models import (
    EnrichmentCycleRow,
    FirstConversationTurnRow,
    SpecificationRevisionRow,
)
from sqlalchemy import func, select
from test_conversation_model import context_inputs as context_inputs
from test_professional_knowledge_http import real_client
from test_professional_knowledge_http import real_config as real_config
from test_prompt_enrichment_http import _message

RU = "Хочу элегантные серьги из белого золота с двумя сапфирами"
EN = "I want elegant white gold earrings with two sapphires"


def raw_message(client, sid, oid, revision_id, text):
    return client.post(
        f"/v1/sessions/{sid}/prompt-enrichment/first-turn/messages",
        headers={"X-Organization-ID": str(oid)},
        json={
            "schema_version": "1.0.0",
            "expected_revision_id": str(revision_id),
            "content": text,
        },
    )


def setup(client, app, text, locale="en", *, raw=False):
    org, _, session = create_hierarchy(client, locale=locale)
    sid = UUID(session.json()["session_id"])
    oid = UUID(org)
    repo = app.state.prompt_enrichment_service.repository
    rev = repo.get_current_revision(sid, oid)
    if raw:
        response = raw_message(client, sid, oid, rev.revision_id, text)
        assert response.status_code == 201, response.json()
        assert response.headers["Cache-Control"] == "no-store, private"
        message = response.json()
        assert message["content"].encode("utf-8") == text.encode("utf-8")
        from jewelai_persistence.models import MessageRow

        with create_session_factory(app.state.engine)() as db:
            assert db.get(MessageRow, UUID(message["message_id"])).content.encode(
                "utf-8"
            ) == text.encode("utf-8")
    else:
        message = _message(client, str(sid), org, text)
    return (
        sid,
        oid,
        dict(
            schema_version="1.0.0",
            message_id=message["message_id"],
            expected_revision_id=str(rev.revision_id),
        ),
    )


def post(client, sid, oid, body):
    return client.post(
        f"/v1/sessions/{sid}/prompt-enrichment/first-turn",
        headers={"X-Organization-ID": str(oid)},
        json=body,
    )


def get(client, sid, oid):
    return client.get(
        f"/v1/sessions/{sid}/prompt-enrichment/first-turn", headers={"X-Organization-ID": str(oid)}
    )


@pytest.mark.parametrize(
    "locale,text",
    [("ru", RU), ("en", EN), ("ru", " \t\n" + RU + "\r\n\t "), ("en", " \t\n" + EN + "\r\n\t ")],
)
def test_first_turn_commits_source_bound_creation_and_exact_reply_reload(
    engine, real_config, locale, text
):
    with real_client(engine, real_config) as (client, app, provider):
        sid, oid, body = setup(client, app, text, locale, raw=True)
        response = post(client, sid, oid, body)
        assert response.status_code == 201, response.json()
        data = response.json()
        assert data["is_current_revision"] is True
        receipt = data["receipt"]
        assert receipt["reply_origin"] == "deterministic_fallback"
        facts = receipt["binding"]["facts"]
        import hashlib

        assert (
            receipt["binding"]["message_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
        )
        assert {f["target"]: f["value"] for f in facts} == {
            "jewelry_type": "earrings",
            "metal.material": "gold",
            "metal.color": "white",
        }
        assert all(text[f["start"] : f["end"]] == f["text"] and f["mapping_ids"] for f in facts)
        repo = app.state.prompt_enrichment_service.repository
        revision = repo.get_current_revision(sid, oid)
        assert revision.design.jewelry_type.value == "earrings"
        assert revision.design.metal.material.value == "gold"
        assert revision.design.center_stone.material is None
        assert revision.design.side_stones == ()
        assert revision.design.jewelry_type.source.message_id == body["message_id"]
        assert get(client, sid, oid).json() == data
        from jewelai_parser.full_message import _source_governance

        # Explicit ST-01 dispatch must not inherit another reader's evidence version.
        with _source_governance("1.2.0"):
            assert get(client, sid, oid).json() == data
        # No second reply or interpretation on repeated initial submission.
        assert post(client, sid, oid, body).status_code == 409
        assert get(client, sid, oid).json() == data
        assert provider.calls == []
    # New app/service/SQLAlchemy sessions: actual disk reload and source replay.
    with real_client(engine, real_config) as (client, app, provider):
        restored = get(client, sid, oid)
        assert restored.status_code == 200, restored.json()
        assert restored.json() == data
        conversation = client.get(
            f"/v1/sessions/{sid}/prompt-enrichment/conversation",
            headers={"X-Organization-ID": str(oid)},
        )
        assert conversation.status_code == 200, conversation.json()
        event = next(
            e for e in conversation.json()["events"] if e.get("message_id") == body["message_id"]
        )
        assert event["text"].encode("utf-8") == text.encode("utf-8")
        assert provider.calls == []


@pytest.mark.parametrize("text", ["", " \t\r\n", "\u00a0\u2003", "x" * 2001])
def test_raw_first_turn_rejects_invalid_text_without_writes(engine, real_config, text):
    with real_client(engine, real_config) as (client, app, provider):
        org, _, session = create_hierarchy(client)
        sid, oid = UUID(session.json()["session_id"]), UUID(org)
        repo = app.state.prompt_enrichment_service.repository
        before = repo.get_current_revision(sid, oid)
        response = raw_message(client, sid, oid, before.revision_id, text)
        assert response.status_code == 422, response.json()
        assert repo.list_messages(sid, oid) == ()
        assert repo.get_current_revision(sid, oid) == before
        assert repo.get_design_session(sid, oid).knowledge_package_id is None
        with create_session_factory(engine)() as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(EnrichmentCycleRow)
                    .where(EnrichmentCycleRow.session_id == sid)
                )
                == 0
            )
        assert provider.calls == []


@pytest.mark.parametrize("locale,text", [("en", EN), ("ru", RU)])
def test_raw_first_turn_exact_parser_limit_and_unchanged_legacy_message(
    engine, real_config, locale, text
):
    with real_client(engine, real_config) as (client, app, provider):
        exact = text + " " * (2000 - len(text))
        sid, oid, body = setup(client, app, exact, locale, raw=True)
        result = post(client, sid, oid, body)
        assert result.status_code == 201, result.json()
        assert get(client, sid, oid).json() == result.json()
        legacy = _message(client, str(sid), str(oid), " \t" + text + "\r\n ")
        assert legacy["content"] == text
        # The legacy contract still permits 4,000 characters and still trims.
        assert _message(client, str(sid), str(oid), "x" * 4000)["content"] == "x" * 4000
        assert provider.calls == []


def test_raw_first_turn_cas_initialized_and_tenant_guards_do_not_append(engine, real_config):
    with real_client(engine, real_config) as (client, app, provider):
        sid, oid, body = setup(client, app, EN, raw=True)
        repo = app.state.prompt_enrichment_service.repository
        before = repo.list_messages(sid, oid)
        assert raw_message(client, sid, oid, uuid4(), RU).status_code == 409
        other_org, _, _ = create_hierarchy(client)
        assert (
            raw_message(client, sid, UUID(other_org), body["expected_revision_id"], RU).status_code
            == 404
        )
        client.headers["Authorization"] = "Bearer test-outsider"
        assert raw_message(client, sid, oid, body["expected_revision_id"], RU).status_code == 404
        client.headers["Authorization"] = "Bearer test-owner-a"
        assert len(repo.list_messages(sid, oid)) == len(before)
        result = post(client, sid, oid, body)
        assert result.status_code == 201, result.json()
        current = repo.get_current_revision(sid, oid)
        assert raw_message(client, sid, oid, current.revision_id, RU).status_code == 409
        assert len(repo.list_messages(sid, oid)) == len(before)
        assert get(client, sid, oid).json() == result.json()
        assert provider.calls == []


def test_raw_first_turn_rechecks_initial_state_at_message_insert(engine, real_config, monkeypatch):
    with real_client(engine, real_config) as (client, app, _):
        # A no-fact turn commits a cycle without changing the canonical revision.
        sid, oid, body = setup(client, app, "Hello")
        repo = app.state.prompt_enrichment_service.repository
        original = repo.create_message

        def raced_insert(row, organization_id, **kwargs):
            assert post(client, sid, oid, body).status_code == 201
            return original(row, organization_id, **kwargs)

        monkeypatch.setattr(repo, "create_message", raced_insert)
        assert raw_message(client, sid, oid, body["expected_revision_id"], EN).status_code == 409
        assert len(repo.list_messages(sid, oid)) == 1
        assert repo.get_current_revision(sid, oid).revision_id == UUID(body["expected_revision_id"])


def test_raw_first_turn_requires_retained_f_pair(engine, real_config):
    from jewelai_persistence.models import DesignSessionRow
    from sqlalchemy import update

    with real_client(engine, real_config) as (client, app, _):
        org, _, session = create_hierarchy(client)
        sid, oid = UUID(session.json()["session_id"]), UUID(org)
        repo = app.state.prompt_enrichment_service.repository
        before = repo.get_current_revision(sid, oid)
        with engine.begin() as db:
            db.execute(
                update(DesignSessionRow)
                .where(DesignSessionRow.session_id == sid)
                .values(question_artifact_version="1.0.0", rules_artifact_version="1.0.0")
            )
        assert raw_message(client, sid, oid, before.revision_id, EN).status_code == 422
        assert repo.list_messages(sid, oid) == ()


@pytest.mark.parametrize(
    "text",
    [
        "Is a white gold ring possible?",
        "Если получится, хочу кольцо из белого золота.",
        "I want a gold or platinum ring.",
        "Compare gold and platinum rings.",
        "Hello",
    ],
)
def test_questions_conditions_comparisons_and_greeting_do_not_select(engine, real_config, text):
    with real_client(engine, real_config) as (client, app, _):
        sid, oid, body = setup(client, app, text)
        before = app.state.prompt_enrichment_service.repository.get_current_revision(sid, oid)
        result = post(client, sid, oid, body)
        assert result.status_code == 201, result.json()
        assert result.json()["receipt"]["binding"]["facts"] == []
        assert (
            app.state.prompt_enrichment_service.repository.get_current_revision(sid, oid) == before
        )


@pytest.mark.parametrize("tamper", ["text", "facts", "pin", "parent", "missing", "reply"])
def test_replay_rejects_tampered_sources_even_with_rehashed_receipt(engine, real_config, tamper):
    from jewelai_persistence.models import MessageRow

    with real_client(engine, real_config) as (client, app, _):
        sid, oid, body = setup(client, app, EN)
        result = post(client, sid, oid, body)
        assert result.status_code == 201, result.json()
        with create_session_factory(engine).begin() as db:
            row = db.get(FirstConversationTurnRow, sid)
            data = deepcopy(row.payload)
            if tamper == "text":
                db.get(MessageRow, UUID(body["message_id"])).content = "I want a platinum ring"
            elif tamper == "missing":
                db.delete(row)
            else:
                if tamper == "facts":
                    data["binding"]["facts"][0]["value"] = "pendant"
                if tamper == "pin":
                    data["binding"]["knowledge_binding"]["runtime_sha256"] = "0" * 64
                if tamper == "reply":
                    data["reply_text"] = "Invented accepted diamond center stone"
                if tamper == "parent":
                    data["binding"]["parent_revision_id"] = str(uuid4())
                data["content_hash"] = evidence_hash(
                    {k: v for k, v in data.items() if k != "content_hash"}
                )
                row.payload, row.content_hash = data, data["content_hash"]
        failed = get(client, sid, oid)
        assert failed.status_code in {404, 422, 500}, failed.json()


def test_final_validation_failure_rolls_back_revision_cycle_pin_and_reply(
    engine, real_config, monkeypatch
):
    import jewelai_api.first_turn as module

    with real_client(engine, real_config) as (client, app, _):
        sid, oid, body = setup(client, app, EN)
        repo = app.state.prompt_enrichment_service.repository
        before = repo.get_current_revision(sid, oid)
        original = module.validate_receipt

        def rejected(payload):
            original(payload)
            raise ValueError("synthetic final receipt rejection")

        monkeypatch.setattr(module, "validate_receipt", rejected)
        result = post(client, sid, oid, body)
        assert result.status_code == 500, result.json()
        assert repo.get_current_revision(sid, oid) == before
        assert repo.get_design_session(sid, oid).knowledge_package_id is None
        with create_session_factory(engine)() as db:
            for table, expected in (
                (FirstConversationTurnRow, 0),
                (EnrichmentCycleRow, 0),
                (SpecificationRevisionRow, 1),
            ):
                assert (
                    db.scalar(
                        select(func.count()).select_from(table).where(table.session_id == sid)
                    )
                    == expected
                )


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "Create white gold earrings.",
            {"jewelry_type": "earrings", "metal.material": "gold", "metal.color": "white"},
        ),
        (
            "Я хочу серьги из белого золота.",
            {"jewelry_type": "earrings", "metal.material": "gold", "metal.color": "white"},
        ),
        (
            "I want a gold ring and I do not want platinum.",
            {"jewelry_type": "ring", "metal.material": "gold"},
        ),
        (
            "Хочу серьги из золота, но не из платины.",
            {"jewelry_type": "earrings", "metal.material": "gold"},
        ),
        ("I want to know about white gold earrings.", {}),
        ("Хочу узнать про серьги из белого золота.", {}),
        ("I want earrings if they are white gold.", {}),
        ("I want earrings, perhaps white gold.", {}),
        ("I want earrings with gold center stones.", {"jewelry_type": "earrings"}),
    ],
)
def test_narrow_binding_independent_controls(context_inputs, text, expected):
    from jewelai_parser import parse_full_message

    from jewelai_api.first_turn import creation_facts

    parsed = parse_full_message(
        text,
        locale="ru" if "Хочу" in text or "Я хочу" in text else "en",
        dictionary=context_inputs["dictionary"],
        knowledge_runtime=context_inputs["active_runtime"].compiled_runtime,
    )
    before = parsed.model_dump_json()
    _, facts = creation_facts(parsed, context_inputs["active_runtime"].compiled_runtime)
    assert {f.target: f.value for f in facts} == expected
    assert parsed.model_dump_json() == before


def test_source_scope_stale_cas_and_tenant_protection(engine, real_config):
    with real_client(engine, real_config) as (client, app, _):
        sid, oid, body = setup(client, app, EN)
        other, _, other_body = setup(client, app, "Other source")
        stolen = {**body, "message_id": other_body["message_id"]}
        assert post(client, sid, oid, stolen).status_code == 404
        assert (
            post(client, sid, oid, {**body, "expected_revision_id": str(uuid4())}).status_code
            == 409
        )
        assert get(client, sid, oid).status_code == 404
        assert post(client, sid, oid, body).status_code == 201
        unauthorized = client.get(
            f"/v1/sessions/{sid}/prompt-enrichment/first-turn",
            headers={"X-Organization-ID": str(oid), "Authorization": "Bearer test-outsider"},
        )
        assert unauthorized.status_code == 404
        assert post(client, other, oid, body).status_code == 404


def test_binding_preserves_existing_authority(context_inputs):
    from jewelai_domain.models import MessageSource

    from jewelai_api.first_turn import CreationFact, creation_design

    revision = context_inputs["committed_revision"]
    source = MessageSource(message_id=str(uuid4()), recorded_at=revision.created_at)
    field = revision.design.jewelry_type
    fact = CreationFact(
        target="jewelry_type",
        value=field.value,
        candidate_id="candidate_1",
        start=0,
        end=4,
        text="ring",
        mapping_ids=("LANG-EN-RING",),
    )
    assert creation_design(revision, (fact,), source) == revision.design
    with pytest.raises(ValueError, match="authority"):
        creation_design(revision, (fact.model_copy(update={"value": "earrings"}),), source)


def test_original_reply_is_historical_after_existing_native_correction(engine, real_config):
    from types import SimpleNamespace

    from test_conversation import correct, read

    with real_client(engine, real_config) as (client, app, _):
        sid, oid, body = setup(client, app, EN)
        result = post(client, sid, oid, body)
        assert result.status_code == 201, result.json()
        receipt = result.json()["receipt"]
        ctx = SimpleNamespace(
            client=client, sid=sid, org=oid, headers={"X-Organization-ID": str(oid)}
        )
        snapshot = read(ctx)
        changed = correct(ctx, snapshot, "Use platinum for the metal material.")
        assert changed["revision"]["design"]["metal"]["material"]["value"] == "platinum"
        latest = get(client, sid, oid)
        assert latest.status_code == 200, latest.json()
        assert latest.json()["receipt"] == receipt
        assert latest.json()["is_current_revision"] is False
    with real_client(engine, real_config) as (client, _, _):
        assert get(client, sid, oid).json() == latest.json()
