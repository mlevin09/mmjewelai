"""No-network production-boundary integration for OpenAI output materialization."""

import base64
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from jewelai_assets import AssetStatus, StoredObject
from jewelai_domain import DesignRevision
from jewelai_generation import (
    ExecutorRegistry,
    GatewayRegistry,
    execute_generation_run,
    execute_generation_run_with_assets,
    generated_asset_id,
)
from jewelai_generation_queue import dispatch_pending_generation_tasks
from jewelai_model_gateway import GenerationConfiguration, GenerationRun, GenerationStatus
from jewelai_model_gateway_openai import (
    OpenAIImageGenerationAdapter,
    OpenAIImageProviderConfig,
)
from jewelai_persistence import (
    Base,
    PersistenceRepository,
    create_database_engine,
    create_session_factory,
)
from jewelai_persistence.models import (
    AssetRow,
    DesignSessionRow,
    GenerationRunRow,
    PromptRevisionRow,
)
from jewelai_prompts import compile_prompt, load_prompt_templates

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
ORG_ID = UUID("20000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("20000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("20000000-0000-4000-8000-000000000003")
PROMPT_ID = UUID("20000000-0000-4000-8000-000000000004")
RUN_ID = UUID("20000000-0000-4000-8000-000000000005")
LEGACY_RUN_ID = UUID("20000000-0000-4000-8000-000000000006")
MODEL = "gpt-image-2.5-sunburst-2026-09-08"
PNG = b"\x89PNG\r\n\x1a\nopenai-integration-output"


class FakeOpenAIClient:
    def __init__(self):
        self.images = self
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(PNG).decode())])


class MemoryObjectStore:
    def __init__(self, events):
        self.objects = {}
        self.events = events
        self.write_count = 0

    def put_if_absent(self, object_key, content, *, content_type, content_hash):
        self.events.append("object_staged")
        self.write_count += 1
        self.objects[object_key] = content
        return StoredObject(
            object_key=object_key,
            content_type=content_type,
            content_hash=content_hash,
            byte_size=len(content),
        )


class CapturingPublisher:
    def __init__(self):
        self.tasks = []

    def publish(self, task):
        self.tasks.append(task)


def test_fake_openai_output_becomes_ready_generated_asset_without_binary_persistence(
    tmp_path,
):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'pipeline.db'}")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    repository = PersistenceRepository(session_factory)
    repository.create_organization(ORG_ID, "Organization", NOW)
    repository.create_project(PROJECT_ID, ORG_ID, "Project", NOW)
    revision = DesignRevision.model_validate_json(
        (ROOT / "specs/jewelry-design-schema/fixtures/valid/ring.json").read_text()
    )
    repository.create_design_session(
        DesignSessionRow(
            session_id=SESSION_ID,
            project_id=PROJECT_ID,
            role_id="retail_client",
            locale="en",
            created_at=NOW,
            updated_at=NOW,
            current_revision_id=revision.revision_id,
            design_schema_version="1.0.0",
            role_artifact_version="1.0.0",
            dictionary_artifact_version="1.0.0",
            question_artifact_version="1.0.0",
            rules_artifact_version="1.0.0",
            prompt_artifact_version="1.0.0",
        ),
        revision,
        organization_id=ORG_ID,
    )
    compiled = compile_prompt(revision, load_prompt_templates(ROOT / "data/prompts/v1.0.0.json"))
    repository.create_prompt_revision(
        PromptRevisionRow(
            prompt_revision_id=PROMPT_ID,
            session_id=SESSION_ID,
            specification_revision_id=revision.revision_id,
            prompt_schema_version=compiled.schema_version,
            compiler_version=compiled.compiler_version,
            template_id=compiled.template_id,
            template_version=compiled.template_version,
            template_artifact_version=compiled.template_artifact_version,
            compiled_text=compiled.prompt_text,
            structured_payload=compiled.model_dump(mode="json"),
            content_hash=compiled.content_hash,
            created_at=NOW,
        ),
        compiled,
        ORG_ID,
        revision.revision_id,
    )
    repository.create_generation_run_with_dispatch(
        GenerationRun(
            generation_run_id=RUN_ID,
            session_id=SESSION_ID,
            prompt_revision_id=PROMPT_ID,
            prompt_content_hash=compiled.content_hash,
            profile_id="openai_image_production",
            profile_version="1.0.0",
            provider="openai",
            model=MODEL,
            configuration=GenerationConfiguration(output_count=1),
            status=GenerationStatus.PENDING,
            created_at=NOW,
        ),
        ORG_ID,
    )
    publisher = CapturingPublisher()
    summary = dispatch_pending_generation_tasks(
        repository, publisher, batch_size=10, clock=lambda: NOW + timedelta(seconds=1)
    )
    assert summary.published == 1
    task = publisher.tasks[0]
    assert (task.generation_run_id, task.session_id, task.organization_id) == (
        RUN_ID,
        SESSION_ID,
        ORG_ID,
    )

    client = FakeOpenAIClient()
    adapter = OpenAIImageGenerationAdapter(
        OpenAIImageProviderConfig(allowed_models=(MODEL,)), client=client
    )
    events = []
    store = MemoryObjectStore(events)
    original_complete = repository.complete_generation_run
    original_create = repository.create_pending_asset

    def complete(*args, **kwargs):
        events.append("run_succeeded")
        return original_complete(*args, **kwargs)

    def create(asset):
        events.append("asset_metadata_created")
        return original_create(asset)

    repository.complete_generation_run = complete
    repository.create_pending_asset = create
    ticks = iter(NOW + timedelta(seconds=value) for value in range(1, 10))

    outcome = execute_generation_run_with_assets(
        repository,
        session_id=task.session_id,
        generation_run_id=task.generation_run_id,
        organization_id=task.organization_id,
        executors=ExecutorRegistry({"openai": adapter}),
        object_store=store,
        clock=ticks.__next__,
    )

    assert outcome.disposition == "succeeded"
    assert outcome.run.status is GenerationStatus.SUCCEEDED
    assert events == ["object_staged", "run_succeeded", "asset_metadata_created"]
    assert store.write_count == 1
    assert client.calls == [
        {
            "model": MODEL,
            "prompt": compiled.prompt_text,
            "n": 1,
            "output_format": "png",
        }
    ]
    asset = outcome.assets[0]
    assert asset.status is AssetStatus.READY
    assert asset.asset_id == generated_asset_id(RUN_ID, 1)
    assert (asset.generation_run_id, asset.generation_output_ordinal) == (RUN_ID, 1)
    assert asset.provider_output_id is None
    assert asset.content_hash == sha256(PNG).hexdigest()
    assert store.objects[asset.object_key] == PNG

    with session_factory() as db:
        run_row = db.get(GenerationRunRow, RUN_ID)
        asset_row = db.get(AssetRow, asset.asset_id)
        persisted_result = json.dumps(run_row.result_payload, sort_keys=True)
        assert "iVBOR" not in persisted_result
        assert "b64_json" not in persisted_result
        assert "url" not in persisted_result
        assert "content" not in AssetRow.__table__.columns
        assert asset_row.byte_size == len(PNG)
        assert asset_row.content_hash == sha256(PNG).hexdigest()

    repository.create_generation_run(
        GenerationRun(
            generation_run_id=LEGACY_RUN_ID,
            session_id=SESSION_ID,
            prompt_revision_id=PROMPT_ID,
            prompt_content_hash=compiled.content_hash,
            profile_id="openai_legacy_guard",
            profile_version="1.0.0",
            provider="openai",
            model=MODEL,
            configuration=GenerationConfiguration(output_count=1),
            status=GenerationStatus.PENDING,
            created_at=NOW,
        ),
        ORG_ID,
    )
    legacy = execute_generation_run(
        repository,
        session_id=SESSION_ID,
        generation_run_id=LEGACY_RUN_ID,
        organization_id=ORG_ID,
        gateways=GatewayRegistry({"openai": adapter}),
        clock=ticks.__next__,
    )
    assert legacy.run.status is GenerationStatus.FAILED
    assert len(client.calls) == 1
    engine.dispose()
