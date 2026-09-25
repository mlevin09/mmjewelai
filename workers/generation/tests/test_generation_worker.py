from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from jewelai_assets import (
    AssetStatus,
    AssetStorageError,
    StoredObject,
)
from jewelai_domain import DesignRevision, unlock_field
from jewelai_domain.models import MessageSource
from jewelai_model_gateway import (
    GeneratedOutputDescriptor,
    GenerationConfiguration,
    GenerationExecution,
    GenerationResult,
    GenerationRun,
    GenerationStatus,
    ProviderRejectedError,
    RetrievedImageOutput,
)
from jewelai_persistence import (
    Base,
    PersistenceRepository,
    create_database_engine,
    create_session_factory,
)
from jewelai_persistence.models import DesignSessionRow, PromptRevisionRow
from jewelai_prompts import compile_prompt, load_prompt_templates

from jewelai_generation import (
    ExecutorRegistry,
    GatewayRegistry,
    execute_generation_run,
    execute_generation_run_with_assets,
    generated_asset_id,
)

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
ORG_ID = UUID("10000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("10000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("10000000-0000-4000-8000-000000000003")
PROMPT_ID = UUID("10000000-0000-4000-8000-000000000004")
RUN_ID = UUID("10000000-0000-4000-8000-000000000005")
SECOND_RUN_ID = UUID("10000000-0000-4000-8000-000000000006")
PNG = b"\x89PNG\r\n\x1a\nworker-output"


class FakeGateway:
    def __init__(self, mode="success"):
        self.mode = mode
        self.calls = 0
        self.requests = []

    def generate(self, request):
        self.calls += 1
        self.requests.append(request)
        if self.mode == "failure":
            raise ProviderRejectedError
        if self.mode == "malformed":
            return {
                "generation_run_id": "99999999-9999-4999-8999-999999999999",
                "provider": request.provider,
                "model": request.model,
                "outputs": [{"ordinal": 1, "media_type": "image"}],
            }
        return GenerationResult(
            generation_run_id=request.generation_run_id,
            provider=request.provider,
            model=request.model,
            provider_request_id="fake-request-1",
            outputs=(
                GeneratedOutputDescriptor(
                    ordinal=1,
                    provider_output_id=f"{request.generation_run_id}-1",
                    width=1024,
                    height=1024,
                ),
            ),
        )


class FakeExecutor:
    def __init__(self, *, payloads=(PNG,), mode="success", events=None):
        self.payloads = payloads
        self.mode = mode
        self.events = events
        self.calls = 0
        self.requests = []

    def execute(self, request):
        if self.events is not None:
            self.events.append("provider_execute")
        self.calls += 1
        self.requests.append(request)
        if self.mode == "failure":
            raise ProviderRejectedError
        descriptors = tuple(
            GeneratedOutputDescriptor(ordinal=ordinal)
            for ordinal in range(1, len(self.payloads) + 1)
        )
        outputs = tuple(
            RetrievedImageOutput(ordinal, None, "image/png", payload)
            for ordinal, payload in enumerate(self.payloads, start=1)
        )
        if self.mode == "mismatch":
            outputs = (RetrievedImageOutput(2, None, "image/png", self.payloads[0]),)
        return GenerationExecution(
            result=GenerationResult(
                generation_run_id=request.generation_run_id,
                provider=request.provider,
                model=request.model,
                outputs=descriptors,
            ),
            outputs=outputs,
        )


class MemoryObjectStore:
    def __init__(self, *, fail=False, fail_on_write=None, events=None):
        self.fail = fail
        self.fail_on_write = fail_on_write
        self.events = events
        self.writes = []
        self.objects = {}

    def put_if_absent(self, object_key, content, *, content_type, content_hash):
        self.writes.append((object_key, content, content_type, content_hash))
        if self.events is not None:
            self.events.append(f"stage_{len(self.writes)}")
        if self.fail or self.fail_on_write == len(self.writes):
            raise AssetStorageError("secret storage failure")
        stored = StoredObject(
            object_key=object_key,
            content_type=content_type,
            content_hash=content_hash,
            byte_size=len(content),
        )
        self.objects[object_key] = content
        return stored


@pytest.fixture
def persisted(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'worker.db'}")
    Base.metadata.create_all(engine)
    repository = PersistenceRepository(create_session_factory(engine))
    repository.create_organization(ORG_ID, "Organization", NOW)
    repository.create_project(PROJECT_ID, ORG_ID, "Project", NOW)
    revision = DesignRevision.model_validate_json(
        (ROOT / "specs/jewelry-design-schema/fixtures/valid/ring.json").read_text()
    )
    session = DesignSessionRow(
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
    )
    repository.create_design_session(session, revision, organization_id=ORG_ID)
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
    run = GenerationRun(
        generation_run_id=RUN_ID,
        session_id=SESSION_ID,
        prompt_revision_id=PROMPT_ID,
        prompt_content_hash=compiled.content_hash,
        profile_id="test_default",
        profile_version="1.0.0",
        provider="test",
        model="deterministic-image-v1",
        configuration=GenerationConfiguration(output_count=1),
        status=GenerationStatus.PENDING,
        created_at=NOW,
    )
    repository.create_generation_run(run, ORG_ID)
    yield repository, revision, compiled
    engine.dispose()


def ticking_clock():
    values = iter((NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)))
    return lambda: next(values)


def advancing_clock():
    count = 0

    def tick():
        nonlocal count
        count += 1
        return NOW + timedelta(seconds=count)

    return tick


def test_success_preserves_exact_prompt_locks_hash_and_is_idempotent(persisted):
    repository, revision, compiled = persisted
    gateway = FakeGateway()
    registry = GatewayRegistry({"test": gateway})
    first = execute_generation_run(
        repository,
        session_id=SESSION_ID,
        generation_run_id=RUN_ID,
        organization_id=ORG_ID,
        gateways=registry,
        clock=ticking_clock(),
    )
    second = execute_generation_run(
        repository,
        session_id=SESSION_ID,
        generation_run_id=RUN_ID,
        organization_id=ORG_ID,
        gateways=registry,
        clock=lambda: NOW + timedelta(seconds=3),
    )
    assert first.disposition == "succeeded"
    assert first.run.status is GenerationStatus.SUCCEEDED
    assert second.disposition == "not_claimed"
    assert gateway.calls == 1
    request = gateway.requests[0]
    assert request.compiled_prompt == compiled
    assert request.compiled_prompt.content_hash == compiled.content_hash
    assert request.compiled_prompt.locked_constraints == compiled.locked_constraints
    assert repository.get_current_revision(SESSION_ID, ORG_ID) == revision


@pytest.mark.parametrize(
    "mode,code",
    [("failure", "provider_rejected"), ("malformed", "gateway_contract_violation")],
)
def test_failure_and_malformed_result_end_failed_without_success_payload(persisted, mode, code):
    repository, _, _ = persisted
    gateway = FakeGateway(mode)
    outcome = execute_generation_run(
        repository,
        session_id=SESSION_ID,
        generation_run_id=RUN_ID,
        organization_id=ORG_ID,
        gateways=GatewayRegistry({"test": gateway}),
        clock=ticking_clock(),
    )
    assert outcome.disposition == "failed"
    assert outcome.run.status is GenerationStatus.FAILED
    assert outcome.run.error_code == code
    assert outcome.run.result is None
    assert "Traceback" not in outcome.run.error_detail


def test_historical_prompt_remains_executable_after_current_revision_advances(persisted):
    repository, revision, compiled = persisted
    later = unlock_field(
        revision,
        "metal.color",
        expected_revision_id=revision.revision_id,
        source=MessageSource(message_id="later-revision", recorded_at=NOW + timedelta(seconds=1)),
        reason="Create a later immutable revision",
        created_at=NOW + timedelta(seconds=1),
    )
    repository.append_revision_cas(SESSION_ID, ORG_ID, revision.revision_id, later)
    gateway = FakeGateway()
    outcome = execute_generation_run(
        repository,
        session_id=SESSION_ID,
        generation_run_id=RUN_ID,
        organization_id=ORG_ID,
        gateways=GatewayRegistry({"test": gateway}),
        clock=lambda: NOW + timedelta(seconds=2 + gateway.calls),
    )
    assert outcome.run.status is GenerationStatus.SUCCEEDED
    assert repository.get_current_revision(SESSION_ID, ORG_ID) == later
    assert gateway.requests[0].compiled_prompt == compiled
    assert gateway.requests[0].compiled_prompt.specification_revision_id == revision.revision_id


def test_generated_asset_id_is_stable_and_lineage_specific():
    assert generated_asset_id(RUN_ID, 1) == generated_asset_id(RUN_ID, 1)
    assert generated_asset_id(RUN_ID, 1) != generated_asset_id(RUN_ID, 2)
    assert generated_asset_id(RUN_ID, 1) != generated_asset_id(SECOND_RUN_ID, 1)


def test_execution_materializes_ready_asset_without_persisting_bytes(persisted):
    repository, _, compiled = persisted
    executor = FakeExecutor()
    store = MemoryObjectStore()

    outcome = execute_generation_run_with_assets(
        repository,
        session_id=SESSION_ID,
        generation_run_id=RUN_ID,
        organization_id=ORG_ID,
        executors=ExecutorRegistry({"test": executor}),
        object_store=store,
        clock=advancing_clock(),
    )

    assert outcome.disposition == "succeeded"
    assert outcome.run.status is GenerationStatus.SUCCEEDED
    assert executor.calls == 1
    assert executor.requests[0].compiled_prompt == compiled
    assert len(outcome.assets) == 1
    asset = outcome.assets[0]
    assert asset.status is AssetStatus.READY
    assert asset.asset_id == generated_asset_id(RUN_ID, 1)
    assert (asset.organization_id, asset.project_id, asset.session_id) == (
        ORG_ID,
        PROJECT_ID,
        SESSION_ID,
    )
    assert (asset.generation_run_id, asset.generation_output_ordinal) == (RUN_ID, 1)
    assert asset.provider_output_id is None
    assert store.writes[0][1] == PNG
    assert len(store.writes) == 1
    persisted_run = repository.get_generation_run(SESSION_ID, RUN_ID, ORG_ID)
    persisted_asset = repository.get_asset(SESSION_ID, asset.asset_id, ORG_ID)
    assert persisted_run.result == outcome.run.result
    assert persisted_asset == asset
    assert "worker-output" not in persisted_run.model_dump_json()
    assert "iVBOR" not in persisted_run.model_dump_json()
    assert "content" not in persisted_asset.model_dump()


def test_duplicate_execution_neither_calls_provider_nor_creates_duplicate_asset(persisted):
    repository, _, _ = persisted
    executor = FakeExecutor()
    store = MemoryObjectStore()
    registry = ExecutorRegistry({"test": executor})
    first = execute_generation_run_with_assets(
        repository,
        session_id=SESSION_ID,
        generation_run_id=RUN_ID,
        organization_id=ORG_ID,
        executors=registry,
        object_store=store,
        clock=advancing_clock(),
    )
    second = execute_generation_run_with_assets(
        repository,
        session_id=SESSION_ID,
        generation_run_id=RUN_ID,
        organization_id=ORG_ID,
        executors=registry,
        object_store=store,
        clock=advancing_clock(),
    )
    assert first.disposition == "succeeded"
    assert second.disposition == "not_claimed"
    assert executor.calls == 1
    assert len(store.writes) == 1
    assert len(repository.list_assets(SESSION_ID, ORG_ID)) == 1


def test_pre_success_storage_failure_fails_run_without_asset_metadata(persisted):
    repository, _, _ = persisted
    executor = FakeExecutor()
    outcome = execute_generation_run_with_assets(
        repository,
        session_id=SESSION_ID,
        generation_run_id=RUN_ID,
        organization_id=ORG_ID,
        executors=ExecutorRegistry({"test": executor}),
        object_store=MemoryObjectStore(fail=True),
        clock=advancing_clock(),
    )
    assert outcome.disposition == "failed"
    assert outcome.run.status is GenerationStatus.FAILED
    assert outcome.run.error_code == "gateway_unavailable"
    assert outcome.run.error_detail == "Generated output could not be durably staged"
    assert outcome.assets == ()
    assert repository.list_assets(SESSION_ID, ORG_ID) == ()
    assert executor.calls == 1
    persisted = repository.get_generation_run(SESSION_ID, RUN_ID, ORG_ID)
    assert persisted.status is GenerationStatus.FAILED


def test_all_outputs_stage_before_success_and_finalize_in_ordinal_order(persisted):
    repository, _, compiled = persisted
    repository.create_generation_run(
        GenerationRun(
            generation_run_id=SECOND_RUN_ID,
            session_id=SESSION_ID,
            prompt_revision_id=PROMPT_ID,
            prompt_content_hash=compiled.content_hash,
            profile_id="test_order",
            profile_version="1.0.0",
            provider="test",
            model="deterministic-image-v1",
            configuration=GenerationConfiguration(output_count=2),
            status=GenerationStatus.PENDING,
            created_at=NOW,
        ),
        ORG_ID,
    )
    events = []
    original_complete = repository.complete_generation_run
    original_create = repository.create_pending_asset
    original_ready = repository.mark_asset_ready

    def complete(*args, **kwargs):
        events.append("complete_run")
        return original_complete(*args, **kwargs)

    def create(asset):
        events.append(f"create_asset_{asset.generation_output_ordinal}")
        return original_create(asset)

    def ready(asset_id, organization_id, ready_at):
        asset = repository.find_asset(asset_id, organization_id)
        events.append(f"ready_asset_{asset.generation_output_ordinal}")
        return original_ready(asset_id, organization_id, ready_at)

    repository.complete_generation_run = complete
    repository.create_pending_asset = create
    repository.mark_asset_ready = ready
    store = MemoryObjectStore(events=events)
    outcome = execute_generation_run_with_assets(
        repository,
        session_id=SESSION_ID,
        generation_run_id=SECOND_RUN_ID,
        organization_id=ORG_ID,
        executors=ExecutorRegistry(
            {"test": FakeExecutor(payloads=(PNG + b"-1", PNG + b"-2"), events=events)}
        ),
        object_store=store,
        clock=advancing_clock(),
    )

    assert outcome.disposition == "succeeded"
    assert events == [
        "provider_execute",
        "stage_1",
        "stage_2",
        "complete_run",
        "create_asset_1",
        "ready_asset_1",
        "create_asset_2",
        "ready_asset_2",
    ]
    assert len(store.writes) == 2


def test_second_output_staging_failure_fails_run_and_leaves_no_asset_rows(persisted):
    repository, _, compiled = persisted
    repository.create_generation_run(
        GenerationRun(
            generation_run_id=SECOND_RUN_ID,
            session_id=SESSION_ID,
            prompt_revision_id=PROMPT_ID,
            prompt_content_hash=compiled.content_hash,
            profile_id="test_partial_stage",
            profile_version="1.0.0",
            provider="test",
            model="deterministic-image-v1",
            configuration=GenerationConfiguration(output_count=2),
            status=GenerationStatus.PENDING,
            created_at=NOW,
        ),
        ORG_ID,
    )
    executor = FakeExecutor(payloads=(PNG + b"-1", PNG + b"-2"))
    store = MemoryObjectStore(fail_on_write=2)
    outcome = execute_generation_run_with_assets(
        repository,
        session_id=SESSION_ID,
        generation_run_id=SECOND_RUN_ID,
        organization_id=ORG_ID,
        executors=ExecutorRegistry({"test": executor}),
        object_store=store,
        clock=advancing_clock(),
    )

    assert outcome.run.status is GenerationStatus.FAILED
    assert outcome.run.error_detail == "Generated output could not be durably staged"
    assert repository.list_assets(SESSION_ID, ORG_ID) == ()
    assert executor.calls == 1
    assert len(store.writes) == 2
    assert tuple(store.objects.values()) == (PNG + b"-1",)


def test_post_success_metadata_failure_leaves_original_bytes_durable(persisted):
    repository, _, _ = persisted
    executor = FakeExecutor()
    store = MemoryObjectStore()
    original_create = repository.create_pending_asset

    def fail_metadata(_asset):
        raise RuntimeError("database unavailable")

    repository.create_pending_asset = fail_metadata
    outcome = execute_generation_run_with_assets(
        repository,
        session_id=SESSION_ID,
        generation_run_id=RUN_ID,
        organization_id=ORG_ID,
        executors=ExecutorRegistry({"test": executor}),
        object_store=store,
        clock=advancing_clock(),
    )
    repository.create_pending_asset = original_create

    assert outcome.disposition == "materialization_failed"
    assert outcome.run.status is GenerationStatus.SUCCEEDED
    assert (
        repository.get_generation_run(SESSION_ID, RUN_ID, ORG_ID).status
        is GenerationStatus.SUCCEEDED
    )
    assert repository.list_assets(SESSION_ID, ORG_ID) == ()
    assert len(store.writes) == 1
    assert store.writes[0][1] == PNG
    assert tuple(store.objects.values()) == (PNG,)
    assert executor.calls == 1


@pytest.mark.parametrize("mode,payload", [("failure", PNG), ("success", b"not-png")])
def test_provider_failure_or_invalid_binary_fails_run_without_asset_or_write(
    persisted, mode, payload
):
    repository, _, _ = persisted
    executor = FakeExecutor(mode=mode, payloads=(payload,))
    store = MemoryObjectStore()
    outcome = execute_generation_run_with_assets(
        repository,
        session_id=SESSION_ID,
        generation_run_id=RUN_ID,
        organization_id=ORG_ID,
        executors=ExecutorRegistry({"test": executor}),
        object_store=store,
        clock=advancing_clock(),
    )
    assert outcome.disposition == "failed"
    assert outcome.run.status is GenerationStatus.FAILED
    assert repository.list_assets(SESSION_ID, ORG_ID) == ()
    assert store.writes == []


def test_mismatched_transient_output_fails_before_completion(persisted):
    repository, _, _ = persisted
    outcome = execute_generation_run_with_assets(
        repository,
        session_id=SESSION_ID,
        generation_run_id=RUN_ID,
        organization_id=ORG_ID,
        executors=ExecutorRegistry({"test": FakeExecutor(mode="mismatch")}),
        object_store=MemoryObjectStore(),
        clock=advancing_clock(),
    )
    assert outcome.disposition == "failed"
    assert outcome.run.error_code == "gateway_contract_violation"


def test_multiple_outputs_materialize_without_swapping(persisted):
    repository, _, compiled = persisted
    repository.create_generation_run(
        GenerationRun(
            generation_run_id=SECOND_RUN_ID,
            session_id=SESSION_ID,
            prompt_revision_id=PROMPT_ID,
            prompt_content_hash=compiled.content_hash,
            profile_id="test_multiple",
            profile_version="1.0.0",
            provider="test",
            model="deterministic-image-v1",
            configuration=GenerationConfiguration(output_count=2),
            status=GenerationStatus.PENDING,
            created_at=NOW,
        ),
        ORG_ID,
    )
    first = PNG + b"-first"
    second = PNG + b"-second"
    store = MemoryObjectStore()
    outcome = execute_generation_run_with_assets(
        repository,
        session_id=SESSION_ID,
        generation_run_id=SECOND_RUN_ID,
        organization_id=ORG_ID,
        executors=ExecutorRegistry({"test": FakeExecutor(payloads=(first, second))}),
        object_store=store,
        clock=advancing_clock(),
    )
    assert outcome.disposition == "succeeded"
    assert tuple(asset.generation_output_ordinal for asset in outcome.assets) == (1, 2)
    assert tuple(asset.asset_id for asset in outcome.assets) == (
        generated_asset_id(SECOND_RUN_ID, 1),
        generated_asset_id(SECOND_RUN_ID, 2),
    )
    assert tuple(write[1] for write in store.writes) == (first, second)
