import json
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import (
    NOW,
    ROOT,
    FakeAssetAccessSigner,
    FakeGenerationTaskPublisher,
    FakePrivateObjectStore,
    FakeTextUnderstandingProvider,
    FakeTokenVerifier,
    create_hierarchy,
)
from fastapi.testclient import TestClient
from jewelai_domain import (
    KNOWLEDGE_RELEASE_QUALIFICATION_VERSION,
    KnowledgeReleaseCandidateKind,
    KnowledgeReleaseCandidateSelection,
    compile_knowledge_library,
    promote_knowledge_runtime,
)
from jewelai_domain.knowledge_storage import KnowledgeArtifactStore
from test_enrichment_persistence import _report
from test_prompt_enrichment_http import _message

from jewelai_api import create_app
from jewelai_api.prompt_enrichment_composition import (
    PromptEnrichmentCompositionError,
    PromptEnrichmentCompositionErrorCode,
)
from jewelai_api.settings import PromptEnrichmentRuntimeConfig, RuntimeSettings

KNOWLEDGE = ROOT / "data" / "knowledge" / "v1" / "three-stone-1.0.0.json"
CONTROLLED_PATHS = (
    "/v1/sessions/{session_id}/prompt-enrichment/initial",
    "/v1/sessions/{session_id}/prompt-enrichment/state",
    "/v1/sessions/{session_id}/prompt-enrichment/clarification-answers",
    "/v1/sessions/{session_id}/prompt-enrichment/corrections",
    "/v1/sessions/{session_id}/prompt-enrichment/final-output",
)


def _release(tmp_path: Path, version: str = "1.0.0"):
    payload = json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
    payload["artifact_version"] = version
    artifact_root = tmp_path / f"knowledge-{version}"
    store = KnowledgeArtifactStore(artifact_root)
    stored = store.publish(payload)
    compiled, _ = compile_knowledge_library(payload)
    report = _report(compiled)
    active = promote_knowledge_runtime(compiled, report)
    evidence_root = tmp_path / f"evidence-{version}"
    evidence_root.mkdir()
    active_path = evidence_root / "active.json"
    report_path = evidence_root / "validation-report.json"
    active_path.write_text(active.model_dump_json(), encoding="utf-8")
    report_path.write_text(report.model_dump_json(), encoding="utf-8")
    config = PromptEnrichmentRuntimeConfig(
        artifact_root=artifact_root,
        candidate=KnowledgeReleaseCandidateSelection(
            package_id=stored.package_id,
            artifact_version=stored.artifact_version,
            kind=KnowledgeReleaseCandidateKind.SYNTHETIC,
        ),
        active_release_path=active_path,
        validation_report_path=report_path,
        qualification_contract_version=KNOWLEDGE_RELEASE_QUALIFICATION_VERSION,
    )
    return config, active, report


def _client(engine, config):
    text_provider = FakeTextUnderstandingProvider()
    application = create_app(
        RuntimeSettings(
            database_url="sqlite+pysqlite://",
            repository_root=ROOT,
            prompt_enrichment=config,
        ),
        engine=engine,
        clock=lambda: NOW,
        uuid_factory=uuid4,
        token_verifier=FakeTokenVerifier(),
        asset_access_signer=FakeAssetAccessSigner(),
        asset_object_store=FakePrivateObjectStore(),
        generation_task_publisher=FakeGenerationTaskPublisher(),
        text_understanding_provider=text_provider,
    )
    client = TestClient(application)
    client.headers["Authorization"] = "Bearer test-owner-a"
    return client, application, text_provider


def test_disabled_default_does_not_compose_or_expose_controlled_routes(engine, monkeypatch):
    def unexpected_composition(*args, **kwargs):
        raise AssertionError("disabled startup must not compose Prompt Enrichment")

    monkeypatch.setattr("jewelai_api.app.compose_prompt_enrichment_runtime", unexpected_composition)
    client, application, _ = _client(engine, None)

    schema = client.get("/openapi.json").json()
    assert all(path not in schema["paths"] for path in CONTROLLED_PATHS)
    assert "/sessions/{session_id}/text-intake" in schema["paths"]
    assert application.state.prompt_enrichment_service is None


def test_disabled_environment_ignores_irrelevant_release_values(monkeypatch):
    monkeypatch.setenv("PROMPT_ENRICHMENT_ENABLED", "false")
    monkeypatch.setenv("PROMPT_ENRICHMENT_KNOWLEDGE_PACKAGE_ID", "../invalid")
    monkeypatch.setenv("PROMPT_ENRICHMENT_ACTIVE_RELEASE_PATH", "not-used")

    settings = RuntimeSettings.from_environment(
        require_oidc=False,
        require_asset_signer=False,
    )

    assert settings.prompt_enrichment is None


@pytest.mark.parametrize(
    "enabled",
    ("TRUE", "1", "yes", " true", "true "),
)
def test_enablement_flag_is_exact(monkeypatch, enabled):
    monkeypatch.setenv("PROMPT_ENRICHMENT_ENABLED", enabled)
    with pytest.raises(ValueError, match="exactly true or false"):
        RuntimeSettings.from_environment(require_oidc=False, require_asset_signer=False)


def test_enabled_environment_requires_complete_exact_configuration(monkeypatch):
    monkeypatch.setenv("PROMPT_ENRICHMENT_ENABLED", "true")
    with pytest.raises(ValueError, match="complete exact release configuration"):
        RuntimeSettings.from_environment(require_oidc=False, require_asset_signer=False)


def test_enabled_environment_loads_exact_typed_release_configuration(monkeypatch, tmp_path):
    config, _, _ = _release(tmp_path)
    values = {
        "PROMPT_ENRICHMENT_ENABLED": "true",
        "PROMPT_ENRICHMENT_KNOWLEDGE_ARTIFACT_ROOT": str(config.artifact_root),
        "PROMPT_ENRICHMENT_KNOWLEDGE_PACKAGE_ID": config.candidate.package_id,
        "PROMPT_ENRICHMENT_KNOWLEDGE_ARTIFACT_VERSION": str(config.candidate.artifact_version),
        "PROMPT_ENRICHMENT_ACTIVE_RELEASE_PATH": str(config.active_release_path),
        "PROMPT_ENRICHMENT_VALIDATION_REPORT_PATH": str(config.validation_report_path),
        "PROMPT_ENRICHMENT_QUALIFICATION_CONTRACT_VERSION": (config.qualification_contract_version),
        "PROMPT_ENRICHMENT_CANDIDATE_KIND": config.candidate.kind.value,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    settings = RuntimeSettings.from_environment(
        require_oidc=False,
        require_asset_signer=False,
    )

    assert settings.prompt_enrichment == config


def test_production_rejects_synthetic_candidate(tmp_path):
    config, _, _ = _release(tmp_path)
    with pytest.raises(ValueError, match="PRODUCTION_INTENDED"):
        RuntimeSettings(
            repository_root=ROOT,
            environment="production",
            prompt_enrichment=config,
        )


def test_enabled_composition_qualifies_release_and_runs_restart_safe_full_http_cycle(
    engine, tmp_path
):
    config, active, report = _release(tmp_path)
    first, first_app, first_legacy_provider = _client(engine, config)

    with first:
        organization_id, _, session_response = create_hierarchy(first)
        session = session_response.json()
        message = _message(
            first,
            session["session_id"],
            organization_id,
            "A white or yellow-gold ring with an oval sapphire center stone and no halo.",
        )
        initial = first.post(
            f"/v1/sessions/{session['session_id']}/prompt-enrichment/initial",
            headers={"X-Organization-ID": organization_id},
            json={
                "expected_revision_id": session["current_revision_id"],
                "message_id": message["message_id"],
            },
        )
        assert initial.status_code == 201, initial.json()
        assert all(path in first.get("/openapi.json").json()["paths"] for path in CONTROLLED_PATHS)
        assert first_legacy_provider.calls == []

    runtime = first_app.state.prompt_enrichment_service
    assert runtime is not None
    assert runtime.knowledge_package_id == config.candidate.package_id
    assert runtime.knowledge_artifact_version == str(config.candidate.artifact_version)
    assert runtime.active_release.runtime_sha256 == active.runtime_sha256
    assert runtime.validation_report.sha256 == report.sha256

    restarted, restarted_app, restarted_legacy_provider = _client(engine, config)
    with restarted:
        state = restarted.get(
            f"/v1/sessions/{session['session_id']}/prompt-enrichment/state",
            headers={"X-Organization-ID": organization_id},
        )
        assert state.status_code == 200, state.json()
        state_body = state.json()
        question = next(
            item
            for item in state_body["clarification_questions"]
            if any(option["value"] == "yellow" for option in item["options"])
        )
        selected = next(option for option in question["options"] if option["value"] == "yellow")
        answer_message = _message(
            restarted,
            session["session_id"],
            organization_id,
            selected["value"],
        )
        answer = restarted.post(
            f"/v1/sessions/{session['session_id']}/prompt-enrichment/clarification-answers",
            headers={"X-Organization-ID": organization_id},
            json={
                "clarification_plan_id": state_body["clarification_plan_id"],
                "clarification_id": question["clarification_id"],
                "decision": "SELECT_OPTION",
                "selected_option": selected["value"],
                "expected_revision_id": state_body["authoritative_revision_id"],
                "answer_id": str(uuid4()),
                "message_id": answer_message["message_id"],
            },
        )
        assert answer.status_code == 200, answer.json()
        answered = answer.json()["state"]
        correction_message = _message(
            restarted,
            session["session_id"],
            organization_id,
            "Change the center stone to emerald cut, but keep the yellow gold. No halo.",
        )
        correction = restarted.post(
            f"/v1/sessions/{session['session_id']}/prompt-enrichment/corrections",
            headers={"X-Organization-ID": organization_id},
            json={
                "expected_revision_id": answered["authoritative_revision_id"],
                "message_id": correction_message["message_id"],
            },
        )
        assert correction.status_code == 200, correction.json()
        final = restarted.get(
            f"/v1/sessions/{session['session_id']}/prompt-enrichment/final-output",
            headers={"X-Organization-ID": organization_id},
        )
        assert final.status_code == 200, final.json()
        assert final.json()["internal_final_prompt"]["schema_version"] == "1.1.0"
        assert restarted_legacy_provider.calls == []
        assert restarted_app.state.prompt_enrichment_service is not runtime


def test_enabled_composition_preserves_organization_scope(engine, tmp_path):
    config, _, _ = _release(tmp_path)
    client, _, _ = _client(engine, config)
    with client:
        organization_id, _, session_response = create_hierarchy(client)
        session_id = session_response.json()["session_id"]
        client.headers["Authorization"] = "Bearer test-unrelated"
        response = client.get(
            f"/v1/sessions/{session_id}/prompt-enrichment/state",
            headers={"X-Organization-ID": organization_id},
        )

    assert response.status_code in {403, 404}


def test_restart_with_different_release_does_not_migrate_existing_session(engine, tmp_path):
    first_config, _, _ = _release(tmp_path, "1.0.0")
    first, _, _ = _client(engine, first_config)
    with first:
        organization_id, _, session_response = create_hierarchy(first)
        session = session_response.json()
        message = _message(first, session["session_id"], organization_id, "I want an oval ring.")
        initial = first.post(
            f"/v1/sessions/{session['session_id']}/prompt-enrichment/initial",
            headers={"X-Organization-ID": organization_id},
            json={
                "expected_revision_id": session["current_revision_id"],
                "message_id": message["message_id"],
            },
        )
        assert initial.status_code == 201

    second_config, _, _ = _release(tmp_path, "1.0.1")
    second, _, _ = _client(engine, second_config)
    with second:
        state = second.get(
            f"/v1/sessions/{session['session_id']}/prompt-enrichment/state",
            headers={"X-Organization-ID": organization_id},
        )

    assert state.status_code == 503
    assert state.json()["error"] == "knowledge_release_unavailable"


def test_tampered_release_blocks_startup_then_clean_startup_succeeds(engine, tmp_path):
    config, _, _ = _release(tmp_path)
    runtime_path = (
        config.artifact_root
        / config.candidate.package_id
        / str(config.candidate.artifact_version)
        / "runtime.json"
    )
    original = runtime_path.read_text(encoding="utf-8")
    runtime_path.write_text(original + " ", encoding="utf-8")

    with pytest.raises(PromptEnrichmentCompositionError) as blocked:
        _client(engine, config)
    assert blocked.value.code == PromptEnrichmentCompositionErrorCode.RELEASE_NOT_QUALIFIED
    assert str(config.artifact_root) not in str(blocked.value)

    runtime_path.write_text(original, encoding="utf-8")
    client, application, _ = _client(engine, config)
    assert application.state.prompt_enrichment_service is not None
    assert all(path in client.get("/openapi.json").json()["paths"] for path in CONTROLLED_PATHS)


@pytest.mark.parametrize("missing", ("active", "report"))
def test_missing_release_evidence_fails_closed(engine, tmp_path, missing):
    config, _, _ = _release(tmp_path)
    path = config.active_release_path if missing == "active" else config.validation_report_path
    path.unlink()

    with pytest.raises(PromptEnrichmentCompositionError) as blocked:
        _client(engine, config)

    assert blocked.value.code == PromptEnrichmentCompositionErrorCode.EVIDENCE_UNAVAILABLE


def test_mismatched_active_envelope_fails_closed(engine, tmp_path):
    config, active, _ = _release(tmp_path)
    payload = active.model_dump(mode="json")
    payload["validation_report_sha256"] = "0" * 64
    config.active_release_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PromptEnrichmentCompositionError) as blocked:
        _client(engine, config)

    assert blocked.value.code == PromptEnrichmentCompositionErrorCode.RELEASE_NOT_QUALIFIED


def test_corrupt_release_evidence_fails_closed_without_payload_leak(engine, tmp_path):
    config, _, _ = _release(tmp_path)
    config.validation_report_path.write_text('{"secret":"not-closed"', encoding="utf-8")

    with pytest.raises(PromptEnrichmentCompositionError) as blocked:
        _client(engine, config)

    assert blocked.value.code == PromptEnrichmentCompositionErrorCode.EVIDENCE_INVALID
    assert "secret" not in str(blocked.value)


def test_unsupported_qualification_contract_is_rejected(tmp_path):
    config, _, _ = _release(tmp_path)
    with pytest.raises(ValueError, match="unsupported"):
        PromptEnrichmentRuntimeConfig(
            artifact_root=config.artifact_root,
            candidate=config.candidate,
            active_release_path=config.active_release_path,
            validation_report_path=config.validation_report_path,
            qualification_contract_version="2.0.0",
        )
