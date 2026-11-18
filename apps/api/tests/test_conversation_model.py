"""Internal adapter/context evidence only, never natural-dialogue acceptance."""

import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from uuid import uuid4

import pytest
from jewelai_domain import DesignRevision
from jewelai_domain.knowledge_activation_v1_1 import ProductionValidationReportV1_1
from jewelai_domain.knowledge_runtime import bind_verified_release
from jewelai_domain.knowledge_storage_v1_1 import KnowledgeArtifactStoreV1_1
from test_professional_knowledge_http import real_config as real_config

from jewelai_api.artifacts import load_runtime_artifacts
from jewelai_api.conversation_model import (
    UntrustedConversationDraft,
    build_conversation_context,
)
from jewelai_api.settings import ArtifactVersions

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def context_inputs(real_config):
    # Existing actual-content fixture/report, isolated test store. This neither
    # activates a live catalog nor claims independent professional qualification.
    store = KnowledgeArtifactStoreV1_1(real_config.artifact_root)
    active = json.loads(real_config.active_release_path.read_bytes())
    report = ProductionValidationReportV1_1.model_validate_json(
        real_config.validation_report_path.read_bytes()
    )
    identity = dict(package_id=report.package_id, artifact_version=str(report.artifact_version))
    verified = store.load_active_runtime(
        **identity, active_release=active, validation_report=report
    )
    binding = bind_verified_release(
        store, **identity, active_release=active, validation_report=report
    )
    fixture = ROOT / "specs/jewelry-design-schema/fixtures/valid/ring.json"
    revision = DesignRevision.model_validate_json(fixture.read_bytes())
    return dict(
        message_id=uuid4(),
        role_id="RR-C25",
        committed_revision=revision,
        dictionary=load_runtime_artifacts(
            ROOT, ArtifactVersions(questions="2.0.0", rules="2.0.0")
        ).dictionary,
        active_runtime=verified,
        release_binding=binding,
    )


@pytest.mark.parametrize(
    ("locale", "text"),
    [
        ("ru", "Хочу элегантные серьги из белого золота с двумя сапфирами"),
        ("en", "I want elegant white gold earrings with two sapphires"),
    ],
)
def test_adapter_context_separates_actual_state_from_recognized_input(context_inputs, locale, text):
    before = context_inputs["committed_revision"].model_dump_json()
    context = build_conversation_context(**context_inputs, original_text=text, locale=locale)
    assert context == build_conversation_context(
        **context_inputs, original_text=text, locale=locale
    )
    assert context.original_text == text
    assert context.committed_revision_json == before
    assert context_inputs["committed_revision"].model_dump_json() == before
    parsed = json.loads(context.source_parse_json)
    assert parsed["parse_version"] == "1.3.0"
    assert parsed["original_text"] == text
    assert {"earrings", "gold", "white", "sapphire"} <= {
        value for candidate in parsed["candidates"] for value in candidate["normalized_values"]
    }
    for candidate in parsed["candidates"]:
        span = candidate["evidence"]
        assert text[span["start"] : span["end"]] == span["text"]
    # Existing Parser subject hints remain evidence, not permission to attach a
    # sapphire or fabricate a group/quantity in this canonical revision.
    assert "sapphire" not in context.committed_revision_json
    assert (
        json.loads(context.knowledge_binding_json)["runtime_sha256"]
        == parsed["knowledge_runtime_sha256"]
    )
    with pytest.raises(FrozenInstanceError):
        context.original_text = "different request"


def test_fake_adapter_returns_only_an_untrusted_draft_and_cannot_save_state(context_inputs):
    context = build_conversation_context(**context_inputs, original_text="Hello", locale="en")
    # The current Parser legitimately retains an unresolved greeting fragment.
    # No lexical fact or applicable positive update may be fabricated from it.
    assert all(
        not candidate["normalized_values"] and candidate["parser_update"] is None
        for candidate in json.loads(context.source_parse_json)["candidates"]
    )

    class FakeModel:
        def draft_reply(self, value):
            assert value is context
            return UntrustedConversationDraft(
                text="Synthetic draft only.",
                provider="test",
                model="deterministic-fake",
                prompt_version="test-only",
            )

    before = context_inputs["committed_revision"].model_dump_json()
    draft = FakeModel().draft_reply(context)
    assert isinstance(draft, UntrustedConversationDraft)
    assert not hasattr(draft, "resulting_revision")
    assert context_inputs["committed_revision"].model_dump_json() == before


def test_context_refuses_tampered_knowledge_binding(context_inputs):
    context_inputs["release_binding"] = context_inputs["release_binding"].model_copy(
        update={"runtime_sha256": "0" * 64}
    )
    with pytest.raises(ValueError):
        build_conversation_context(**context_inputs, original_text="Hello", locale="en")
