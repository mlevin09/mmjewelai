from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from jewelai_domain import DesignRevision, unlock_field
from jewelai_domain.models import MessageSource
from jewelai_model_gateway import (
    GeneratedOutputDescriptor,
    GenerationConfiguration,
    GenerationResult,
    GenerationRun,
    GenerationStatus,
    ProviderRejectedError,
)
from jewelai_persistence import (
    Base,
    PersistenceRepository,
    create_database_engine,
    create_session_factory,
)
from jewelai_persistence.models import DesignSessionRow, PromptRevisionRow
from jewelai_prompts import compile_prompt, load_prompt_templates

from jewelai_generation import GatewayRegistry, execute_generation_run

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
ORG_ID = UUID("10000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("10000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("10000000-0000-4000-8000-000000000003")
PROMPT_ID = UUID("10000000-0000-4000-8000-000000000004")
RUN_ID = UUID("10000000-0000-4000-8000-000000000005")


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
