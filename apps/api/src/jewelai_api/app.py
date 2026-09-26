"""FastAPI app factory and thin HTTP routing boundary."""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jewelai_assets import (
    AssetAccessContractError,
    AssetAccessUnavailableError,
    AssetNotReadyError,
    PrivateObjectAccessSigner,
    SignedAssetReadAccess,
)
from jewelai_assets_gcs import GcsPrivateObjectAccessSigner
from jewelai_auth import (
    AuthenticatedPrincipal,
    AuthenticationError,
    AuthenticationUnavailableError,
    AuthorizationDeniedError,
    LastOwnerError,
    MembershipConflictError,
    MembershipNotFoundError,
    TokenVerifier,
)
from jewelai_auth_oidc import OidcJwtVerifier
from jewelai_domain import UnknownRoleError, UnsupportedLocaleError
from jewelai_generation_queue import GenerationTaskPublisher
from jewelai_generation_queue_gcp import CloudTasksGenerationPublisher
from jewelai_model_gateway import GenerationRun
from jewelai_parser import ParserProposal
from jewelai_persistence import (
    GenerationRetryNotAllowedError,
    GenerationStateConflictError,
    NotFoundError,
    StaleRevisionError,
    create_database_engine,
    create_session_factory,
)
from jewelai_persistence.repository import PersistenceRepository
from pydantic import ValidationError
from sqlalchemy import Engine

from .artifacts import ArtifactConfigurationError, load_runtime_artifacts
from .generation import GenerationProfileRegistry, UnknownGenerationProfileError
from .schemas import (
    AssetListResponse,
    AssetResponse,
    CreateAssetAccessRequest,
    CreateGenerationRunRequest,
    CreateMembershipRequest,
    CreateMessageRequest,
    CreateOrganizationRequest,
    CreateProjectRequest,
    CreatePromptRevisionRequest,
    CreateSessionRequest,
    EvaluateRequest,
    EvaluationResponse,
    GenerationRunListResponse,
    MembershipListResponse,
    MembershipResponse,
    MeResponse,
    MessageResponse,
    OrganizationResponse,
    ParserProposalRequest,
    ProjectResponse,
    PromptRevisionListResponse,
    PromptRevisionResponse,
    RetryGenerationRunRequest,
    RevisionListResponse,
    RevisionTransitionRequest,
    SessionResponse,
    UpdateMembershipRequest,
)
from .services import (
    InvalidTransitionError,
    LockedFieldConflictError,
    RuntimeService,
    SpecificationNotReadyError,
)
from .settings import RuntimeSettings


def create_app(
    settings: RuntimeSettings | None = None,
    *,
    engine: Engine | None = None,
    clock: Callable[[], datetime] | None = None,
    uuid_factory: Callable[[], UUID] | None = None,
    generation_profiles: GenerationProfileRegistry | None = None,
    token_verifier: TokenVerifier | None = None,
    asset_access_signer: PrivateObjectAccessSigner | None = None,
    generation_task_publisher: GenerationTaskPublisher | None = None,
) -> FastAPI:
    settings = settings or RuntimeSettings.from_environment(
        require_oidc=token_verifier is None,
        require_asset_signer=asset_access_signer is None,
        require_generation_publisher=generation_task_publisher is None,
    )
    if token_verifier is None:
        if settings.oidc is None:
            raise ValueError("OIDC configuration is required when no token verifier is injected")
        token_verifier = OidcJwtVerifier(settings.oidc)
    if asset_access_signer is None:
        if settings.asset_signing is None:
            raise ValueError(
                "GCS Asset signing configuration is required when no Asset access "
                "signer is injected"
            )
        asset_access_signer = GcsPrivateObjectAccessSigner(settings.asset_signing)
    if generation_task_publisher is None:
        if settings.generation_tasks is None:
            raise ValueError(
                "Cloud Tasks configuration is required when no generation publisher is injected"
            )
        generation_task_publisher = CloudTasksGenerationPublisher(settings.generation_tasks)
    engine = engine or create_database_engine(settings.database_url)
    artifacts = load_runtime_artifacts(settings.repository_root, settings.artifacts)
    repository = PersistenceRepository(create_session_factory(engine))
    service = RuntimeService(
        repository,
        artifacts,
        clock=clock,
        uuid_factory=uuid_factory,
        generation_profiles=generation_profiles,
        asset_access_signer=asset_access_signer,
        generation_task_publisher=generation_task_publisher,
    )
    app = FastAPI(title="JewelAI V2 API", version="1.0.0")
    app.state.service = service
    app.state.engine = engine

    @app.exception_handler(NotFoundError)
    async def not_found_handler(_, exc):
        return _error_response(404, "not_found", str(exc))

    @app.exception_handler(AuthenticationError)
    async def authentication_handler(_, exc):
        return _error_response(
            401, "authentication_failed", str(exc), headers={"WWW-Authenticate": "Bearer"}
        )

    @app.exception_handler(AuthenticationUnavailableError)
    async def authentication_unavailable_handler(_, exc):
        return _error_response(503, "authentication_unavailable", str(exc))

    @app.exception_handler(AuthorizationDeniedError)
    async def authorization_handler(_, exc):
        return _error_response(403, "authorization_denied", str(exc))

    @app.exception_handler(MembershipNotFoundError)
    async def membership_not_found_handler(_, exc):
        return _error_response(404, "not_found", str(exc))

    @app.exception_handler(MembershipConflictError)
    async def membership_conflict_handler(_, exc):
        return _error_response(409, "membership_conflict", str(exc))

    @app.exception_handler(LastOwnerError)
    async def last_owner_handler(_, exc):
        return _error_response(409, "last_owner", str(exc))

    @app.exception_handler(StaleRevisionError)
    async def stale_handler(_, exc):
        return _error_response(409, "stale_revision", str(exc))

    @app.exception_handler(GenerationStateConflictError)
    async def generation_state_handler(_, exc):
        return _error_response(409, "generation_state_conflict", str(exc))

    @app.exception_handler(GenerationRetryNotAllowedError)
    async def generation_retry_handler(_, __):
        return _error_response(
            409,
            "generation_retry_not_allowed",
            "Generation run is not eligible for retry",
        )

    @app.exception_handler(AssetNotReadyError)
    async def asset_not_ready_handler(_, __):
        return _error_response(
            409,
            "asset_not_ready",
            "Asset is not ready for temporary read access",
        )

    async def asset_access_unavailable_handler(_, __):
        return _error_response(
            503,
            "asset_access_unavailable",
            "Temporary asset read access is unavailable",
        )

    app.add_exception_handler(AssetAccessUnavailableError, asset_access_unavailable_handler)
    app.add_exception_handler(AssetAccessContractError, asset_access_unavailable_handler)

    @app.exception_handler(UnknownGenerationProfileError)
    async def generation_profile_handler(_, exc):
        return _error_response(422, "unknown_generation_profile", str(exc))

    @app.exception_handler(LockedFieldConflictError)
    async def locked_handler(_, exc):
        return _error_response(409, "locked_field_conflict", str(exc))

    @app.exception_handler(SpecificationNotReadyError)
    async def not_ready_handler(_, exc):
        from fastapi.responses import JSONResponse

        decision = exc.decision
        return JSONResponse(
            status_code=409,
            content={
                "error": "specification_not_ready",
                "detail": str(exc),
                "decision": decision.decision,
                "reason_code": decision.reason_code,
                "target": decision.target,
                "concrete_target": decision.concrete_target,
            },
        )

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

    bearer = HTTPBearer(auto_error=False)

    def get_authenticated_principal(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> AuthenticatedPrincipal:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise AuthenticationError("Bearer authentication is required")
        identity = token_verifier.verify(credentials.credentials)
        return request.app.state.service.resolve_identity(identity)

    Authenticated = Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)]

    def require_header_organization(
        principal: Authenticated,
        organization_id: Annotated[UUID, Header(alias="X-Organization-ID")],
    ) -> UUID:
        service.require_organization_member(organization_id, principal.principal_id)
        return organization_id

    AuthorizedOrganization = Annotated[UUID, Depends(require_header_organization)]

    @app.get("/me", response_model=MeResponse)
    def get_me(principal: Authenticated):
        return service.get_me(principal)

    @app.post("/organizations", response_model=OrganizationResponse, status_code=201)
    def create_organization(request: CreateOrganizationRequest, principal: Authenticated):
        return service.create_organization(request.name, principal.principal_id)

    @app.get("/organizations/{organization_id}/memberships", response_model=MembershipListResponse)
    def list_memberships(organization_id: UUID, principal: Authenticated):
        return service.list_memberships(organization_id, principal.principal_id)

    @app.post(
        "/organizations/{organization_id}/memberships",
        response_model=MembershipResponse,
        status_code=201,
    )
    def add_membership(
        organization_id: UUID, request: CreateMembershipRequest, principal: Authenticated
    ):
        return service.add_membership(
            organization_id, principal.principal_id, request.principal_id, request.role
        )

    @app.patch(
        "/organizations/{organization_id}/memberships/{principal_id}",
        response_model=MembershipResponse,
    )
    def update_membership(
        organization_id: UUID,
        principal_id: UUID,
        request: UpdateMembershipRequest,
        principal: Authenticated,
    ):
        return service.update_membership(
            organization_id, principal.principal_id, principal_id, request.role
        )

    @app.delete("/organizations/{organization_id}/memberships/{principal_id}", status_code=204)
    def delete_membership(
        organization_id: UUID, principal_id: UUID, principal: Authenticated
    ) -> Response:
        service.delete_membership(organization_id, principal.principal_id, principal_id)
        return Response(status_code=204)

    @app.post(
        "/organizations/{organization_id}/projects",
        response_model=ProjectResponse,
        status_code=201,
    )
    def create_project(
        organization_id: UUID, request: CreateProjectRequest, principal: Authenticated
    ):
        service.require_organization_member(organization_id, principal.principal_id)
        return service.create_project(organization_id, request.name)

    @app.post("/projects/{project_id}/sessions", response_model=SessionResponse, status_code=201)
    def create_session(
        project_id: UUID,
        request: CreateSessionRequest,
        organization_id: AuthorizedOrganization,
    ):
        return service.create_session(project_id, organization_id, request)

    @app.get("/sessions/{session_id}", response_model=SessionResponse)
    def get_session(
        session_id: UUID,
        organization_id: AuthorizedOrganization,
    ):
        return service.get_session(session_id, organization_id)

    @app.post("/sessions/{session_id}/messages", response_model=MessageResponse, status_code=201)
    def create_message(
        session_id: UUID,
        request: CreateMessageRequest,
        organization_id: AuthorizedOrganization,
    ):
        return service.create_message(session_id, organization_id, request.content)

    @app.post("/sessions/{session_id}/parser-proposals", response_model=ParserProposal)
    def create_parser_proposal(
        session_id: UUID,
        request: ParserProposalRequest,
        organization_id: AuthorizedOrganization,
    ):
        return service.create_parser_proposal(session_id, organization_id, request)

    @app.get("/sessions/{session_id}/revisions", response_model=RevisionListResponse)
    def list_revisions(
        session_id: UUID,
        organization_id: AuthorizedOrganization,
    ):
        return RevisionListResponse(
            revisions=repository.list_revisions(session_id, organization_id)
        )

    @app.get("/sessions/{session_id}/revisions/{revision_id}")
    def get_revision(
        session_id: UUID,
        revision_id: UUID,
        organization_id: AuthorizedOrganization,
    ):
        return repository.get_revision(session_id, revision_id, organization_id)

    @app.post(
        "/sessions/{session_id}/prompt-revisions",
        response_model=PromptRevisionResponse,
        status_code=201,
    )
    def create_prompt_revision(
        session_id: UUID,
        request: CreatePromptRevisionRequest,
        organization_id: AuthorizedOrganization,
    ):
        return service.create_prompt_revision(session_id, organization_id, request)

    @app.get(
        "/sessions/{session_id}/prompt-revisions",
        response_model=PromptRevisionListResponse,
    )
    def list_prompt_revisions(
        session_id: UUID,
        organization_id: AuthorizedOrganization,
    ):
        return service.list_prompt_revisions(session_id, organization_id)

    @app.get(
        "/sessions/{session_id}/prompt-revisions/{prompt_revision_id}",
        response_model=PromptRevisionResponse,
    )
    def get_prompt_revision(
        session_id: UUID,
        prompt_revision_id: UUID,
        organization_id: AuthorizedOrganization,
    ):
        return service.get_prompt_revision(session_id, prompt_revision_id, organization_id)

    @app.post(
        "/sessions/{session_id}/generation-runs", response_model=GenerationRun, status_code=201
    )
    def create_generation_run(
        session_id: UUID,
        request: CreateGenerationRunRequest,
        organization_id: AuthorizedOrganization,
    ):
        return service.create_generation_run(session_id, organization_id, request)

    @app.post(
        "/sessions/{session_id}/generation-runs/{generation_run_id}/retry",
        response_model=GenerationRun,
        status_code=201,
    )
    def retry_generation_run(
        session_id: UUID,
        generation_run_id: UUID,
        request: RetryGenerationRunRequest,
        response: Response,
        organization_id: AuthorizedOrganization,
    ):
        run, created = service.retry_generation_run(
            session_id, generation_run_id, organization_id, request
        )
        if not created:
            response.status_code = 200
        return run

    @app.get("/sessions/{session_id}/generation-runs", response_model=GenerationRunListResponse)
    def list_generation_runs(
        session_id: UUID,
        organization_id: AuthorizedOrganization,
    ):
        return service.list_generation_runs(session_id, organization_id)

    @app.get(
        "/sessions/{session_id}/generation-runs/{generation_run_id}",
        response_model=GenerationRun,
    )
    def get_generation_run(
        session_id: UUID,
        generation_run_id: UUID,
        organization_id: AuthorizedOrganization,
    ):
        return service.get_generation_run(session_id, generation_run_id, organization_id)

    @app.get("/sessions/{session_id}/assets", response_model=AssetListResponse)
    def list_assets(
        session_id: UUID,
        organization_id: AuthorizedOrganization,
    ):
        return service.list_assets(session_id, organization_id)

    @app.get("/sessions/{session_id}/assets/{asset_id}", response_model=AssetResponse)
    def get_asset(
        session_id: UUID,
        asset_id: UUID,
        organization_id: AuthorizedOrganization,
    ):
        return service.get_asset(session_id, asset_id, organization_id)

    @app.post(
        "/sessions/{session_id}/assets/{asset_id}/access",
        response_model=SignedAssetReadAccess,
    )
    def create_asset_access(
        session_id: UUID,
        asset_id: UUID,
        request: CreateAssetAccessRequest,
        response: Response,
        organization_id: AuthorizedOrganization,
    ):
        access = service.create_asset_read_access(
            session_id,
            asset_id,
            organization_id,
            request.ttl_seconds,
        )
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        return access

    @app.post("/sessions/{session_id}/revisions")
    def transition_revision(
        session_id: UUID,
        request: RevisionTransitionRequest,
        organization_id: AuthorizedOrganization,
    ):
        return service.transition_revision(session_id, organization_id, request)

    @app.post("/sessions/{session_id}/evaluate", response_model=EvaluationResponse)
    def evaluate(
        session_id: UUID,
        request: EvaluateRequest,
        organization_id: AuthorizedOrganization,
    ):
        return service.evaluate(session_id, organization_id, request)

    return app


def _error_response(
    status_code: int, code: str, detail: str, *, headers: dict[str, str] | None = None
):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status_code,
        content={"error": code, "detail": detail},
        headers=headers,
    )
