"""Real recovered catalogs through the persisted HTTP consumer; no paid providers.

Authentication is the existing test verifier, NOT real Identity Platform login.
The report is actual bounded catalog evidence; it is not a six-check dummy fixture.
"""

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from conftest import (
    FakeAssetAccessSigner,
    FakeGenerationTaskPublisher,
    FakePrivateObjectStore,
    FakeTextUnderstandingProvider,
    FakeTokenVerifier,
    create_hierarchy,
)
from jewelai_domain.knowledge_activation_v1_1 import (
    ProductionValidationReportV1_1,
    promote_knowledge_runtime_v1_1,
)
from jewelai_domain.knowledge_library_v1_1 import compile_knowledge_library_v1_1
from jewelai_domain.knowledge_qualification import KnowledgeReleaseCandidateSelection
from jewelai_domain.knowledge_storage_v1_1 import KnowledgeArtifactStoreV1_1
from test_conversation import correct, read
from test_f04_http import answer
from test_f05_history import initial
from test_f05_preview import output

from jewelai_api import create_app
from jewelai_api.settings import ArtifactVersions, PromptEnrichmentRuntimeConfig, RuntimeSettings

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/knowledge"))


@pytest.fixture
def real_config(tmp_path):
    from build_p010_symmetry_draft import extended_draft
    from prepare_preprod_integration import ARTIFACT_VERSION, PACKAGE_ID

    candidate = extended_draft().model_copy(
        update={"package_id": PACKAGE_ID, "artifact_version": ARTIFACT_VERSION}
    )
    runtime = compile_knowledge_library_v1_1(candidate)[0]
    store = KnowledgeArtifactStoreV1_1(tmp_path / "knowledge")
    store.publish(candidate)
    report_path = ROOT / "docs/prompt-enrichment/preprod-knowledge/validation-report-1.0.0.json"
    report = ProductionValidationReportV1_1.model_validate_json(report_path.read_bytes())
    active = promote_knowledge_runtime_v1_1(runtime, report)
    (tmp_path / "active.json").write_text(active.model_dump_json())
    return PromptEnrichmentRuntimeConfig(
        artifact_root=tmp_path / "knowledge",
        candidate=KnowledgeReleaseCandidateSelection(
            **{
                "package_id": PACKAGE_ID,
                "artifact_version": ARTIFACT_VERSION,
                "kind": "PRODUCTION_INTENDED",
            }
        ),
        active_release_path=tmp_path / "active.json",
        validation_report_path=report_path,
        qualification_contract_version="1.0.0",
        knowledge_contract_version="1.1.0",
    )


@contextmanager
def real_client(engine, config):
    from fastapi.testclient import TestClient

    provider = FakeTextUnderstandingProvider()
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
        text_understanding_provider=provider,
    )
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer test-owner-a"
        yield client, app, provider


def context(client, app, session, org):
    runtime = app.state.prompt_enrichment_service
    return SimpleNamespace(
        client=client,
        app=app,
        runtime=runtime,
        repo=runtime.repository,
        sid=UUID(session),
        org=UUID(org),
        headers={"X-Organization-ID": org},
    )


@pytest.mark.parametrize(
    "locale,text",
    [
        (
            "en",
            "A white gold ring with an oval diamond center stone in prong setting. "
            "Center stone 8 x 6 x 4 mm.",
        ),
        (
            "ru",
            "Кольцо из белого золота с овальным бриллиантом. "
            "Center stone 8 x 6 x 4 mm. Prong setting.",
        ),
        (
            "en",
            "Кольцо из белого золота with an oval diamond center stone. "
            "Center stone 8 x 6 x 4 mm. Prong setting.",
        ),
    ],
)
def test_real_catalog_initial_output_and_scope(engine, real_config, locale, text):
    with real_client(engine, real_config) as (client, app, provider):
        org, _, session = create_hierarchy(client, locale=locale)
        ctx = context(client, app, session.json()["session_id"], org)
        initial(ctx, "F", text)
        snapshot = read(ctx)
        design = snapshot["revision"]["design"]
        assert design["metal"]["material"]["value"] == "gold"
        assert design["metal"]["color"]["value"] == "white"
        assert design["center_stone"]["material"]["value"] == "diamond"
        assert design["center_stone"]["shape"]["value"] == "oval"
        result = output(ctx, snapshot["state"], projection=False)
        assert result.status_code == 200, result.json()
        assert result.json()["internal_final_prompt"]["schema_version"] == "4.0.0"
        binding = ctx.repo.get_knowledge_release_pin(ctx.sid, ctx.org)
        assert binding is not None
        # Every real parse binds the configured real semantic runtime, never a small fixture.
        bound = ctx.runtime._for_session(ctx.sid, ctx.org)._load_release()
        assert bound.package_id == "jewelai.preprod.recovered_core"
        assert (
            bound.runtime_sha256
            == json.loads(real_config.validation_report_path.read_text())["runtime_sha256"]
        )
        forbidden = client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/conversation",
            headers={**ctx.headers, "Authorization": "Bearer test-outsider"},
        )
        assert forbidden.status_code == 404
        assert provider.calls == []


def test_real_catalog_browser_preflight_and_final_output(engine, real_config):
    with real_client(engine, real_config) as (client, app, provider):
        org, _, session = create_hierarchy(client)
        ctx = context(client, app, session.json()["session_id"], org)
        initial(
            ctx,
            "F",
            "A white gold ring with an oval diamond center stone in prong setting. "
            "Center stone 8 x 6 x 4 mm.",
        )
        snapshot = read(ctx)
        path = f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output?output_version=4.0.0"
        origin = "https://preprod.jewellai.online"
        preflight = client.options(
            path,
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,if-match,x-organization-id",
            },
        )
        assert preflight.status_code == 200
        result = client.get(
            path,
            headers={
                **ctx.headers,
                "Origin": origin,
                "If-Match": snapshot["state"]["current_frame"]["history_root_sha256"],
            },
        )
        assert result.status_code == 200, result.json()
        assert result.headers["access-control-allow-origin"] == origin
        assert result.json()["description"]["text"]
        assert result.json()["internal_final_prompt"]["schema_version"] == "4.0.0"
        assert result.json()["internal_final_prompt"]["prompt_text"]
        assert provider.calls == []


def test_real_catalog_keep_correction_and_restart(engine, real_config):
    with real_client(engine, real_config) as (client, app, provider):
        org, _, session = create_hierarchy(client)
        ctx = context(client, app, session.json()["session_id"], org)
        initial(
            ctx,
            "F",
            "A white gold ring with an oval diamond center stone in prong setting. "
            "Center stone 8 x 6 x 4 mm.",
        )
        before = read(ctx)
        stone = before["revision"]["design"]["center_stone"]
        protected = correct(ctx, before, "Keep the center stone unchanged.")
        changed = correct(ctx, protected, "Change the metal to platinum.")
        assert changed["revision"]["design"]["metal"]["material"]["value"] == "platinum"
        assert changed["revision"]["design"]["center_stone"] == stone
        assert changed["state"]["protection_projection"]["roots"]
        saved = output(ctx, changed["state"], projection=False)
        assert saved.status_code == 200, saved.json()
        assert provider.calls == []
    with real_client(engine, real_config) as (client, app, provider):
        restored = context(client, app, str(ctx.sid), org)
        assert read(restored) == changed
        assert output(restored, changed["state"], projection=False).json() == saved.json()
        assert (
            correct(restored, changed, "A yellow gold ring.")["revision"]["design"]["center_stone"]
            == stone
        )
        assert provider.calls == []


def test_real_catalog_material_clarification(engine, real_config):
    from test_f04_http import initial as material_initial

    with real_client(engine, real_config) as (client, app, provider):
        org, _, session = create_hierarchy(client)
        ctx = context(client, app, session.json()["session_id"], org)
        state = material_initial(ctx, "A gold or platinum ring.")
        response, _ = answer(ctx, state, value="gold")
        assert response.status_code == 200, response.json()
        assert read(ctx)["revision"]["design"]["metal"]["material"]["value"] == "gold"
        assert provider.calls == []


def test_real_catalog_parametric_and_unsupported_no_fabrication(engine, real_config):
    with real_client(engine, real_config) as (client, app, provider):
        org, _, session = create_hierarchy(client)
        ctx = context(client, app, session.json()["session_id"], org)
        initial(
            ctx,
            "F",
            "A gold ring with an oval diamond center stone in prong setting. "
            "Center stone weight 1 ct.",
        )
        snapshot = read(ctx)
        stone = snapshot["revision"]["design"]["center_stone"]
        assert stone["material"]["value"] == "diamond"
        assert stone["shape"]["value"] == "oval"
        assert stone["weight"] is not None, stone
        assert stone["weight"]["value"] == {"value": 1.0, "unit": "ct"}
        cycle = ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)[-1]
        refs = cycle.result.parametric_references
        assert refs and any(
            r.dimensions.length_mm == 7.0 and r.dimensions.width_mm == 5.0 for r in refs
        ), stone
        assert all(r.record_ids and r.source_ids and r.uncertainty for r in refs)
        stone = snapshot["revision"]["design"]["center_stone"]
        assert stone["dimensions"] is None or stone["dimensions"]["value"] is None
        changed = correct(ctx, snapshot, "Use unobtainium.")
        assert changed["revision"] == snapshot["revision"]
        assert any(
            e["kind"] == "user" and e["text"] == "Use unobtainium." for e in changed["events"]
        )
        assert any(
            e["kind"] == "decision" and e["outcome"] == "DEFERRED" for e in changed["events"]
        )
        assert provider.calls == []
