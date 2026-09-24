"""FastAPI app factory and thin HTTP routing boundary."""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header
from jewelai_domain import UnknownRoleError, UnsupportedLocaleError
from jewelai_persistence import (
    NotFoundError,
    StaleRevisionError,
    create_database_engine,
    create_session_factory,
)
from jewelai_persistence.repository import PersistenceRepository
from pydantic import ValidationError
from sqlalchemy import Engine

from .artifacts import ArtifactConfigurationError, load_runtime_artifacts
from .schemas import (
    CreateOrganizationRequest,
    CreateProjectRequest,
    CreateSessionRequest,
    EvaluateRequest,
    EvaluationResponse,
    OrganizationResponse,
    ProjectResponse,
    RevisionListResponse,
    RevisionTransitionRequest,
    SessionResponse,
)
from .services import InvalidTransitionError, LockedFieldConflictError, RuntimeService
from .settings import RuntimeSettings


def create_app(
    settings: RuntimeSettings | None = None,
    *,
    engine: Engine | None = None,
    clock: Callable[[], datetime] | None = None,
    uuid_factory: Callable[[], UUID] | None = None,
) -> FastAPI:
    settings = settings or RuntimeSettings.from_environment()
    engine = engine or create_database_engine(settings.database_url)
    artifacts = load_runtime_artifacts(settings.repository_root, settings.artifacts)
    repository = PersistenceRepository(create_session_factory(engine))
    service = RuntimeService(repository, artifacts, clock=clock, uuid_factory=uuid_factory)
    app = FastAPI(title="JewelAI V2 API", version="1.0.0")
    app.state.service = service
    app.state.engine = engine

    @app.exception_handler(NotFoundError)
    async def not_found_handler(_, exc):
        return _error_response(404, "not_found", str(exc))

    @app.exception_handler(StaleRevisionError)
    async def stale_handler(_, exc):
        return _error_response(409, "stale_revision", str(exc))

    @app.exception_handler(LockedFieldConflictError)
    async def locked_handler(_, exc):
        return _error_response(409, "locked_field_conflict", str(exc))

    async def invalid_handler(_, exc):
        return _error_response(422, "invalid_transition", str(exc))

    app.add_exception_handler(InvalidTransitionError, invalid_handler)
    app.add_exception_handler(ValidationError, invalid_handler)
    app.add_exception_handler(ValueError, invalid_handler)

    @app.exception_handler(UnknownRoleError)
    async def role_handler(_, exc):
        return _error_response(422, "invalid_role", str(exc))

    @app.exception_handler(UnsupportedLocaleError)
    async def locale_handler(_, exc):
        return _error_response(422, "unsupported_locale", str(exc))

    @app.exception_handler(ArtifactConfigurationError)
    async def artifact_handler(_, exc):
        return _error_response(500, "invalid_artifact_configuration", str(exc))

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/organizations", response_model=OrganizationResponse, status_code=201)
    def create_organization(request: CreateOrganizationRequest):
        return service.create_organization(request.name)

    @app.post(
        "/organizations/{organization_id}/projects",
        response_model=ProjectResponse,
        status_code=201,
    )
    def create_project(organization_id: UUID, request: CreateProjectRequest):
        return service.create_project(organization_id, request.name)

    @app.post("/projects/{project_id}/sessions", response_model=SessionResponse, status_code=201)
    def create_session(
        project_id: UUID,
        request: CreateSessionRequest,
        organization_id: Annotated[UUID, Header(alias="X-Organization-ID")],
    ):
        return service.create_session(project_id, organization_id, request)

    @app.get("/sessions/{session_id}", response_model=SessionResponse)
    def get_session(
        session_id: UUID,
        organization_id: Annotated[UUID, Header(alias="X-Organization-ID")],
    ):
        return service.get_session(session_id, organization_id)

    @app.get("/sessions/{session_id}/revisions", response_model=RevisionListResponse)
    def list_revisions(
        session_id: UUID,
        organization_id: Annotated[UUID, Header(alias="X-Organization-ID")],
    ):
        return RevisionListResponse(
            revisions=repository.list_revisions(session_id, organization_id)
        )

    @app.get("/sessions/{session_id}/revisions/{revision_id}")
    def get_revision(
        session_id: UUID,
        revision_id: UUID,
        organization_id: Annotated[UUID, Header(alias="X-Organization-ID")],
    ):
        return repository.get_revision(session_id, revision_id, organization_id)

    @app.post("/sessions/{session_id}/revisions")
    def transition_revision(
        session_id: UUID,
        request: RevisionTransitionRequest,
        organization_id: Annotated[UUID, Header(alias="X-Organization-ID")],
    ):
        return service.transition_revision(session_id, organization_id, request)

    @app.post("/sessions/{session_id}/evaluate", response_model=EvaluationResponse)
    def evaluate(
        session_id: UUID,
        request: EvaluateRequest,
        organization_id: Annotated[UUID, Header(alias="X-Organization-ID")],
    ):
        return service.evaluate(session_id, organization_id, request)

    return app


def _error_response(status_code: int, code: str, detail: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content={"error": code, "detail": detail})
