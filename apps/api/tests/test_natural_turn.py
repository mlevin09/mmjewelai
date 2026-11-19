"""US-01 real persisted HTTP with injected model; never real-model acceptance."""

import json
from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
from conftest import (
    ROOT,
    FakeAssetAccessSigner,
    FakeGenerationTaskPublisher,
    FakePrivateObjectStore,
    FakeTextUnderstandingProvider,
    FakeTokenVerifier,
    create_hierarchy,
)
from fastapi.testclient import TestClient
from jewelai_domain.clarification_state import evidence_hash
from jewelai_persistence import create_session_factory
from jewelai_persistence.models import InitialConversationTurnRow, MessageRow
from test_first_turn import EN, RU
from test_professional_knowledge_http import real_config as real_config

from jewelai_api import create_app
from jewelai_api.conversation_model import UntrustedConversationDraft
from jewelai_api.conversation_qwen import QwenConversationConfig
from jewelai_api.natural_turn import REPLY_VERSION
from jewelai_api.semantic_proposal import SemanticChange, SemanticProposal, SourceSpan
from jewelai_api.settings import ArtifactVersions, RuntimeSettings


@contextmanager
def real_client(engine, config, *, conversation_model=None):
    """Existing native app/fixtures with a scoped new adapter injection, no shared helper edit."""
    legacy = FakeTextUnderstandingProvider()
    app = create_app(
        RuntimeSettings(
            database_url="sqlite+pysqlite://",
            repository_root=ROOT,
            artifacts=ArtifactVersions(questions="2.0.0", rules="2.0.0"),
            prompt_enrichment=config,
            web_allowed_origins=("https://preprod.jewellai.online",),
        ),
        engine=engine,
        token_verifier=FakeTokenVerifier(),
        asset_access_signer=FakeAssetAccessSigner(),
        asset_object_store=FakePrivateObjectStore(),
        generation_task_publisher=FakeGenerationTaskPublisher(),
        text_understanding_provider=legacy,
        conversation_model=conversation_model,
    )
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer test-owner-a"
        yield client, app, legacy


class Model:
    """Protocol fake: claims/proposals are verified by real SO/Matrix/storage."""

    def __init__(self, *, meaning="selection", reply=None):
        self.calls = []
        self.meaning = meaning
        self.reply = reply
        self.before_reply = None
        self.config = QwenConversationConfig(
            endpoint="http://127.0.0.1:8080/v1/chat/completions",
            model="qwen3-1.7b-q4_k_m",
            model_sha256="0" * 64,
            runtime_build="test-only-not-live",
        )

    def interpret(self, context):
        self.calls.append(("meaning", context))
        # Synthetic MODEL output based only on raw source/typed user input.
        # Never constructs output from the independent Parser's candidates.
        import re

        raw = context.original_text
        changes = []
        for pattern, target, value, owner in [
            (r"earrings|серьги", "jewelry_type", "earrings", "product"),
            (r"gold|золота|золото", "metal.material", "gold", "product_body"),
            (r"white|белого|белое", "metal.color", "white", "product_body"),
            (r"sapphires|сапфирами", "stone.material", "sapphire", "stone"),
            (r"two|двумя", "stone.count", 2, "stone"),
        ]:
            match = re.search(pattern, raw, re.I)
            if match:
                changes.append(
                    SemanticChange(
                        proposal_id=f"p{len(changes)}",
                        target=target,
                        value=value,
                        component=owner,
                        disposition="question" if self.meaning == "information" else self.meaning,
                        source=SourceSpan(start=match.start(), end=match.end(), text=match.group()),
                    )
                )
        for index, selected in enumerate(
            json.loads(context.semantic_evidence_json)["typed_selections"]
        ):
            changes = [c for c in changes if c.target != "jewelry_type"]
            changes.append(
                SemanticChange(
                    proposal_id="typed",
                    target="jewelry_type",
                    value=selected["value"],
                    component="product",
                    disposition="selection",
                    selection_index=index,
                )
            )
        return SemanticProposal(
            based_on_revision=json.loads(context.committed_revision_json)["revision_id"],
            intent="information" if self.meaning == "information" else "creation",
            changes=tuple(changes),
        )

    def draft_reply(self, context):
        self.calls.append(("reply", context))
        if self.before_reply:
            self.before_reply(context)
        state = json.loads(context.committed_revision_json)["design"]
        ru = context.locale == "ru"
        body = "Здравствуйте! Обсудим вашу идею." if ru else "Hello! Let's discuss your idea."
        if state.get("jewelry_type") and state["jewelry_type"].get("value") == "earrings":
            body = "Сохранены серьги." if ru else "Your earrings are saved."
            if state["metal"]["material"] and state["metal"]["material"].get("value") == "gold":
                body = (
                    "Сохранены серьги из белого золота."
                    if ru
                    else "Your white gold earrings are saved."
                )
        observations = json.loads(context.semantic_evidence_json)["observations"]
        if any(o["kind"] in {"stone", "count"} for o in observations):
            body += (
                " Как распределить упомянутые сапфиры: два на пару или на каждую серьгу?"
                if ru
                else " Are the two mentioned sapphires for the pair or for each earring?"
            )
        return UntrustedConversationDraft(
            text=self.reply or body,
            provider="qwen",
            model="qwen3-1.7b-q4_k_m",
            prompt_version=REPLY_VERSION,
        )


def prepare(client, app, locale, text, *, selected=None, transcript=None):
    org, _, session = create_hierarchy(client, locale=locale)
    sid, oid = UUID(session.json()["session_id"]), UUID(org)
    repo = app.state.prompt_enrichment_service.repository
    parent = repo.get_current_revision(sid, oid)
    request = dict(
        schema_version="2.0.0",
        turn_id=str(uuid4()),
        expected_revision_id=str(parent.revision_id),
        original_text=text,
        selections=[{"target": "jewelry_type", "value": selected}] if selected else [],
        transcript=transcript,
    )
    return sid, oid, parent, request


def post(client, sid, oid, request):
    return client.post(
        f"/v1/sessions/{sid}/prompt-enrichment/first-turn",
        headers={"X-Organization-ID": str(oid)},
        json=request,
    )


def get(client, sid, oid):
    return client.get(
        f"/v1/sessions/{sid}/prompt-enrichment/first-turn?turn_version=2.0.0",
        headers={"X-Organization-ID": str(oid)},
    )


@pytest.mark.parametrize("locale", ["ru", "en"])
@pytest.mark.parametrize("mode", ["text", "dropdown", "mixed", "transcript"])
def test_all_inputs_share_so_matrix_commit_reply_and_disk_restart(
    engine, real_config, locale, mode
):
    text = RU if locale == "ru" else EN
    selected = None
    transcript = None
    if mode == "dropdown":
        text, selected = "", "earrings"
    elif mode == "mixed":
        text, selected = ("белое золото" if locale == "ru" else "white gold"), "earrings"
    elif mode == "transcript":
        transcript = {"kind": "editable_transcript", "user_edited": True}
    if text:
        text = " \t\n" + text + "\r\n "
    model = Model()
    with real_client(engine, real_config, conversation_model=model) as (client, app, legacy):
        sid, oid, parent, request = prepare(
            client, app, locale, text, selected=selected, transcript=transcript
        )
        repo = app.state.prompt_enrichment_service.repository

        def after_commit(context):
            # A separate SQLAlchemy read can observe the already committed State.
            saved = repo.get_current_revision(sid, oid)
            assert saved.design.jewelry_type.value == "earrings"
            assert context.committed_revision_json == saved.model_dump_json()

        model.before_reply = after_commit
        result = post(client, sid, oid, request)
        assert result.status_code == 201, result.json()
        body = result.json()
        assert body["schema_version"] == "2.0.0"
        assert body["commit_status"] == "committed" and body["delivery_status"] == "delivered"
        assert body["delivered_reply"]["origin"] == "model"
        assert body["evidence"]["meaning_origin"] == "model"
        assert [phase for phase, _ in model.calls] == ["meaning", "reply"]
        assert body["evidence"]["request"] == request
        current = repo.get_current_revision(sid, oid)
        assert current.design.jewelry_type.value == "earrings"
        assert current.design.center_stone.material is None and current.design.side_stones == ()
        if mode != "dropdown":
            assert current.design.metal.material.value == "gold"
            assert current.design.metal.color.value == "white"
        assert any(term in body["current_brief"].lower() for term in ["earrings", "серьги"])
        if mode in {"text", "transcript"}:
            observed = body["evidence"]["observations"]
            assert any(
                o["kind"] == "stone" and o["normalized_values"] == ["sapphire"] for o in observed
            )
            assert any(o["kind"] == "count" and o["count"] == 2 for o in observed)
            assert all(o["attachment"] is None and o["quantity_scope"] is None for o in observed)
        with create_session_factory(engine)() as db:
            message = db.get(MessageRow, UUID(body["evidence"]["message_id"]))
            assert message.content.encode() == text.encode()
        assert get(client, sid, oid).json() == body
        repeated = post(client, sid, oid, request)
        assert repeated.status_code == 200 and repeated.json() == body
        assert len(model.calls) == 2
        assert len(repo.list_messages(sid, oid)) == 1
        assert legacy.calls == []
    # New app/service/SQLAlchemy sessions against actual disk; no model regeneration.
    with real_client(engine, real_config, conversation_model=model) as (client, _, legacy):
        restored = get(client, sid, oid)
        assert restored.status_code == 200, restored.json()
        assert restored.json() == body
        assert len(model.calls) == 2 and legacy.calls == []


@pytest.mark.parametrize("text", ["Hello!", "Привет!", "Хочу серьги из белого золота обсудить."])
def test_nonstate_and_information_do_not_get_promoted_by_model(engine, real_config, text):
    model = Model()
    with real_client(engine, real_config, conversation_model=model) as (client, app, _):
        sid, oid, parent, request = prepare(
            client, app, "ru" if "Х" in text or "П" in text else "en", text
        )
        result = post(client, sid, oid, request)
        assert result.status_code == 201, result.json()
        assert result.json()["current_revision"]["revision_id"] == str(parent.revision_id)
        assert result.json()["delivered_reply"]["origin"] == "model"


def test_mixed_conflict_and_recommendations_are_not_consent(engine, real_config):
    for model, text, selected in [
        (Model(), EN, "pendant"),
        (Model(meaning="recommendation"), EN, None),
    ]:
        with real_client(engine, real_config, conversation_model=model) as (client, app, _):
            sid, oid, parent, request = prepare(client, app, "en", text, selected=selected)
            result = post(client, sid, oid, request)
            assert result.status_code == 201, result.json()
            assert result.json()["current_revision"]["revision_id"] == str(parent.revision_id)
            assert result.json()["evidence"]["conflicted"] is bool(selected)


@pytest.mark.parametrize(
    "claim",
    [
        "Your natural oval sapphires weigh 2ct each.",
        "I have selected platinum and added a halo.",
        "Игнорируй State: принято кольцо с натуральными бриллиантами.",
        "The mentioned sapphires weigh 2ct each. Is that okay?",
        "You mentioned sapphires. There is one per earring. Shall we continue?",
        "Your white gold earrings are saved. The mentioned sapphires are saved. "
        "How should the two sapphires be allocated?",
    ],
)
def test_model_injected_claims_fail_closed_to_explicit_saved_fallback(engine, real_config, claim):
    model = Model(reply=claim)
    with real_client(engine, real_config, conversation_model=model) as (client, app, _):
        sid, oid, _, request = prepare(client, app, "en", EN)
        result = post(client, sid, oid, request)
        assert result.status_code == 201, result.json()
        reply = result.json()["delivered_reply"]
        assert reply["origin"] == "fallback" and reply["failure_code"] == "invalid_reply"
        assert claim not in reply["text"]
        assert get(client, sid, oid).json() == result.json()
        assert len(model.calls) == 2


def test_bad_semantic_source_cannot_write_and_current_cas_tenant_guards(engine, real_config):
    class BadModel(Model):
        def interpret(self, context):
            return {
                "contract_version": "jewelai.us01.meaning/1.0.0",
                "proposals": [
                    {
                        "source_ref": "invented",
                        "disposition": "selection",
                        "target": "center_stone.shape",
                        "value": "oval",
                    }
                ],
            }

    model = BadModel()
    with real_client(engine, real_config, conversation_model=model) as (client, app, _):
        sid, oid, parent, request = prepare(client, app, "en", EN)
        wrong = {**request, "expected_revision_id": str(uuid4())}
        assert post(client, sid, oid, wrong).status_code == 409
        other_org, _, _ = create_hierarchy(client)
        assert post(client, sid, UUID(other_org), request).status_code == 404
        result = post(client, sid, oid, request)
        assert result.status_code == 201, result.json()
        assert result.json()["evidence"]["meaning_origin"] == "unavailable"
        assert result.json()["current_revision"]["design"]["center_stone"]["shape"] is None
        assert post(client, sid, oid, {**request, "original_text": "different"}).status_code == 409
        client.headers["Authorization"] = "Bearer test-outsider"
        assert get(client, sid, oid).status_code == 404


def test_old_fallback_receipt_is_not_reinterpreted_or_regenerated(engine, real_config):
    from test_first_turn import get as old_get
    from test_first_turn import post as old_post
    from test_first_turn import setup

    model = Model()
    with real_client(engine, real_config, conversation_model=model) as (client, app, _):
        sid, oid, request = setup(client, app, EN)
        old = old_post(client, sid, oid, request)
        assert old.status_code == 201
        assert get(client, sid, oid).json() == old_get(client, sid, oid).json() == old.json()
        assert model.calls == []


def test_information_question_never_commits_discussed_cut(engine, real_config):
    class Information(Model):
        def interpret(self, context):
            self.calls.append(("meaning", context))
            text = context.original_text
            word = "огранки"
            start = text.index(word)
            return SemanticProposal(
                based_on_revision=json.loads(context.committed_revision_json)["revision_id"],
                intent="information",
                changes=(
                    SemanticChange(
                        proposal_id="cut-question",
                        target="stone.cut",
                        value="oval",
                        component="stone",
                        disposition="question",
                        source=SourceSpan(start=start, end=start + len(word), text=word),
                    ),
                ),
            )

    model = Information(
        reply="Вы упомянули сапфиры. Какую огранку вы рассматриваете? "
        "Без проверенных данных я не буду утверждать профессиональную рекомендацию."
    )
    with real_client(engine, real_config, conversation_model=model) as (client, app, _):
        sid, oid, before, request = prepare(
            client, app, "ru", "Какие огранки подходят для сапфиров?"
        )
        response = post(client, sid, oid, request)
        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["current_revision"]["revision_id"] == str(before.revision_id)
        assert body["evidence"]["arbitration"][0]["outcome"] == "NO_COMMIT"
        assert body["delivered_reply"]["origin"] == "model"
        assert get(client, sid, oid).json() == body


def test_model_failure_after_state_commit_returns_truthful_retained_reply(engine, real_config):
    from jewelai_api.conversation_qwen import ConversationProviderError

    class UnavailableReply(Model):
        def draft_reply(self, context):
            self.calls.append(("reply", context))
            raise ConversationProviderError("upstream_timeout")

    model = UnavailableReply()
    with real_client(engine, real_config, conversation_model=model) as (client, app, _):
        sid, oid, before, request = prepare(client, app, "en", EN)
        response = post(client, sid, oid, request)
        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["current_revision"]["revision_id"] != str(before.revision_id)
        assert body["current_revision"]["design"]["jewelry_type"]["value"] == "earrings"
        assert body["delivered_reply"]["origin"] == "fallback"
        assert body["delivered_reply"]["failure_code"] == "upstream_timeout"
        assert post(client, sid, oid, request).json() == get(client, sid, oid).json() == body
        assert len(model.calls) == 2
    with real_client(engine, real_config, conversation_model=None) as (client, _, _):
        assert get(client, sid, oid).json() == body


@pytest.mark.parametrize("tamper", ["message", "meaning", "reply", "model"])
def test_rehashed_current_source_or_delivery_tampering_is_rejected(engine, real_config, tamper):
    from copy import deepcopy

    model = Model()
    with real_client(engine, real_config, conversation_model=model) as (client, app, _):
        sid, oid, _, request = prepare(client, app, "en", EN)
        assert post(client, sid, oid, request).status_code == 201
        with create_session_factory(engine).begin() as db:
            row = db.get(InitialConversationTurnRow, sid)
            if tamper == "message":
                db.get(MessageRow, row.message_id).content = "Different user source"
            elif tamper == "meaning":
                payload = json.loads(json.dumps(row.input_payload))
                payload["meaning"]["changes"][0]["source"]["text"] = "invented"
                row.input_payload, row.input_hash = payload, evidence_hash(payload)
            else:
                payload = deepcopy(row.reply_payload)
                payload["text" if tamper == "reply" else "model"] = "unverified"
                row.reply_payload, row.reply_hash = payload, evidence_hash(payload)
        result = get(client, sid, oid)
        assert result.status_code == 500, result.json()
        assert result.json()["error"] == "invalid_durable_history"
        assert len(model.calls) == 2


def test_rejected_precommit_read_is_atomic_and_delivery_failure_is_honest(
    engine, real_config, monkeypatch
):
    from jewelai_persistence import EnrichmentIntegrityError

    from jewelai_api import natural_turn

    model = Model()
    with real_client(engine, real_config, conversation_model=model) as (client, app, _):
        sid, oid, parent, request = prepare(client, app, "en", EN)
        repo = app.state.prompt_enrichment_service.repository
        original = natural_turn._evaluate_record

        def reject(*args):
            raise EnrichmentIntegrityError("synthetic precommit validation failure")

        monkeypatch.setattr(natural_turn, "_evaluate_record", reject)
        assert post(client, sid, oid, request).status_code == 500
        assert repo.get_current_revision(sid, oid) == parent
        assert repo.list_messages(sid, oid) == ()
        with create_session_factory(engine)() as db:
            assert db.get(InitialConversationTurnRow, sid) is None
        monkeypatch.setattr(natural_turn, "_evaluate_record", original)

        def delivery_failed(**kwargs):
            raise EnrichmentIntegrityError("synthetic delivery persistence failure")

        original_delivery = repo.commit_initial_conversation_reply
        monkeypatch.setattr(repo, "commit_initial_conversation_reply", delivery_failed)
        assert post(client, sid, oid, request).status_code == 500
        current = repo.get_current_revision(sid, oid)
        assert current.design.jewelry_type.value == "earrings"
        result = get(client, sid, oid)
        assert result.status_code == 200
        assert result.json()["commit_status"] == "committed"
        assert result.json()["delivery_status"] == "pending"
        assert result.json()["delivered_reply"] is None
        calls = len(model.calls)
        monkeypatch.setattr(repo, "commit_initial_conversation_reply", original_delivery)
        recovered = post(client, sid, oid, request)
        assert recovered.status_code == 200, recovered.json()
        assert recovered.json()["delivery_status"] == "delivered"
        assert len(model.calls) == calls + 1 and model.calls[-1][0] == "reply"
        assert repo.get_current_revision(sid, oid) == current
        assert len(repo.list_messages(sid, oid)) == 1
        assert get(client, sid, oid).json() == recovered.json()


def test_existing_locked_value_cannot_be_replaced_by_meaning_or_reply(engine, real_config):
    from jewelai_domain.models import Explicit, MessageSource
    from jewelai_domain.revisions import confirm_field, lock_field, revise_design
    from test_prompt_enrichment_http import _message

    model = Model()
    with real_client(engine, real_config, conversation_model=model) as (client, app, _):
        sid, oid, parent, request = prepare(client, app, "en", EN)
        repo = app.state.prompt_enrichment_service.repository
        msg = _message(client, str(sid), str(oid), "Keep platinum locked.")
        source = MessageSource(
            message_id=msg["message_id"], recorded_at=app.state.prompt_enrichment_service._clock()
        )
        data = parent.design.model_dump(mode="json")
        data["metal"]["material"] = Explicit[str](value="platinum", source=source).model_dump(
            mode="json"
        )
        revision = revise_design(
            parent,
            type(parent.design).model_validate(data),
            expected_revision_id=parent.revision_id,
            source=source,
            reason="test explicit lock",
            created_at=source.recorded_at,
        )
        repo.append_revision_cas(sid, oid, parent.revision_id, revision)
        for transition in (confirm_field, lock_field):
            next_revision = transition(
                revision,
                "metal.material",
                expected_revision_id=revision.revision_id,
                source=source,
                reason="test explicit authority transition",
                created_at=source.recorded_at,
            )
            repo.append_revision_cas(sid, oid, revision.revision_id, next_revision)
            revision = next_revision
        request["expected_revision_id"] = str(revision.revision_id)
        result = post(client, sid, oid, request)
        assert result.status_code == 201, result.json()
        field = repo.get_current_revision(sid, oid).design.metal.material
        assert field.value == "platinum" and field.confirmed and field.locked
        decisions = result.json()["evidence"]["arbitration"]
        assert any(
            d["reason"] == "protected_state" and d["outcome"] == "NO_COMMIT" for d in decisions
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"original_text": " \t\n", "selections": []},
        {"original_text": "x" * 2001},
        {"selections": [{"target": "jewelry_type", "value": "not_qualified"}]},
        {
            "original_text": "",
            "selections": [{"target": "jewelry_type", "value": "earrings"}],
            "transcript": {"kind": "editable_transcript", "user_edited": False},
        },
    ],
)
def test_invalid_inputs_fail_before_model_or_writes(engine, real_config, changes):
    model = Model()
    with real_client(engine, real_config, conversation_model=model) as (client, app, _):
        sid, oid, parent, request = prepare(client, app, "en", EN)
        result = post(client, sid, oid, {**request, **changes})
        assert result.status_code == 422, result.json()
        assert model.calls == []
        repo = app.state.prompt_enrichment_service.repository
        assert repo.list_messages(sid, oid) == () and repo.get_current_revision(sid, oid) == parent


@pytest.mark.parametrize(
    "locale,wording",
    [
        ("en", "I understand your idea: white gold earrings."),
        ("en", "Your white gold earrings are saved. The mentioned sapphires are not saved."),
        ("ru", "Понял ваш замысел. Это серьги из белого золота."),
    ],
)
def test_genuine_new_model_wording_is_checked_and_saved_not_replaced_by_template(
    engine, real_config, locale, wording
):
    class FluentModel(Model):
        def draft_reply(self, context):
            self.calls.append(("reply", context))
            tail = (
                "Как распределить упомянутые сапфиры?"
                if context.locale == "ru"
                else "How should the mentioned sapphires be allocated?"
            )
            return UntrustedConversationDraft(
                text=wording + "\n\n" + tail,
                provider="qwen",
                model="qwen3-1.7b-q4_k_m",
                prompt_version=REPLY_VERSION,
            )

    model = FluentModel()
    with real_client(engine, real_config, conversation_model=model) as (client, app, _):
        sid, oid, _, request = prepare(client, app, locale, RU if locale == "ru" else EN)
        result = post(client, sid, oid, request)
        assert result.status_code == 201, result.json()
        reply = result.json()["delivered_reply"]
        assert reply["origin"] == "model" and reply["text"].startswith(wording)
        assert reply["text"] not in json.loads(model.calls[-1][1].safe_reply_options_json)
        assert get(client, sid, oid).json() == result.json()


def test_compact_qwen_wire_uses_real_so_commit_and_retained_reply(engine, real_config):
    import httpx

    from jewelai_api.conversation_qwen import QwenConversationAdapter

    sent = []

    def transport(request):
        packet = json.loads(request.content)
        context = json.loads(packet["messages"][1]["content"])
        sent.append(packet)
        if len(sent) == 1:
            assert packet["response_format"] == {"type": "json_object"}
            assert "arbitration" not in context and "source_parse" not in context
            raw = {
                "intent": "creation",
                "changes": [
                    {
                        "target": target,
                        "value": value,
                        "component": owner,
                        "disposition": "selection",
                        "source_phrase": phrase,
                    }
                    for target, value, owner, phrase in [
                        ("jewelry_type", "earrings", "product", "earrings"),
                        ("metal.material", "gold", "product_body", "gold"),
                        ("metal.color", "white", "product_body", "white"),
                        ("stone.material", "sapphire", "stone", "sapphires"),
                        ("stone.count", 2, "stone", "two"),
                    ]
                ],
            }
        else:
            assert {r["target"]: r["value"] for r in context["state"]} == {
                "jewelry_type": "earrings",
                "metal.material": "gold",
                "metal.color": "white",
            }
            raw = {
                "text": "Your white gold earrings are saved. Are the two mentioned sapphires "
                "for the pair or for each earring?"
            }
        return httpx.Response(
            200,
            json={
                "model": "qwen3-1.7b-q4_k_m",
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(raw)}}],
            },
        )

    model = QwenConversationAdapter(
        Model().config, client=httpx.Client(transport=httpx.MockTransport(transport))
    )
    with real_client(engine, real_config, conversation_model=model) as (client, app, _):
        sid, oid, before, request = prepare(client, app, "en", " \n" + EN + "\r\n")
        result = post(client, sid, oid, request)
        assert result.status_code == 201, result.json()
        body = result.json()
        assert body["delivered_reply"]["origin"] == "model"
        assert [d["outcome"] for d in body["evidence"]["arbitration"]] == [
            "ACCEPT",
            "ACCEPT",
            "ACCEPT",
            "CLARIFY",
            "CLARIFY",
        ]
        assert body["current_revision"]["revision_id"] != str(before.revision_id)
        assert body["evidence"]["model_runtime"]["sampling"]["top_k"] == 20
        for fact in body["evidence"]["eligible_facts"]:
            assert request["original_text"][fact["start"] : fact["end"]] == fact["text"]
        assert get(client, sid, oid).json() == post(client, sid, oid, request).json() == body
        assert len(sent) == 2
    with real_client(engine, real_config, conversation_model=None) as (client, _, _):
        assert get(client, sid, oid).json() == body
