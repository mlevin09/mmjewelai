"""HTTP contracts; persisted rows and domain snapshots remain separate types."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from jewelai_domain import (
    AskDecision,
    AssumeDecision,
    AvailableKnowledgeFact,
    BlockDecision,
    DeriveDecision,
    Design,
    DesignRevision,
    ProposedDomainUpdate,
    ReadyDecision,
    RenderedQuestion,
)
from jewelai_domain.models import MessageSource
from jewelai_parser import ParserCandidate
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Target = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
MessageContent = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000, pattern=r"\S")
]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class CreateOrganizationRequest(ApiModel):
    name: Name


class CreateProjectRequest(ApiModel):
    name: Name


class CreateSessionRequest(ApiModel):
    role_id: str
    locale: str


class OrganizationResponse(ApiModel):
    organization_id: UUID
    name: str
    created_at: datetime


class ProjectResponse(ApiModel):
    project_id: UUID
    organization_id: UUID
    name: str
    created_at: datetime


class ArtifactPins(ApiModel):
    design_schema: str
    roles: str
    dictionary: str
    questions: str
    rules: str


class SessionResponse(ApiModel):
    session_id: UUID
    project_id: UUID
    role_id: str
    locale: str
    created_at: datetime
    updated_at: datetime
    current_revision_id: UUID
    artifacts: ArtifactPins


class CreateMessageRequest(ApiModel):
    content: MessageContent


class MessageResponse(ApiModel):
    message_id: UUID
    session_id: UUID
    actor: Literal["user"]
    content: str
    created_at: datetime


class ParserProposalRequest(ApiModel):
    expected_revision_id: UUID
    message_id: UUID
    candidate: ParserCandidate


class EditRevisionRequest(ApiModel):
    action: Literal["edit"]
    expected_revision_id: UUID
    proposed_design: Design
    source: MessageSource
    reason: Reason


class ConfirmRevisionRequest(ApiModel):
    action: Literal["confirm"]
    expected_revision_id: UUID
    target: Target
    source: MessageSource
    reason: Reason


class LockRevisionRequest(ApiModel):
    action: Literal["lock"]
    expected_revision_id: UUID
    target: Target
    source: MessageSource
    reason: Reason


class UnlockRevisionRequest(ApiModel):
    action: Literal["unlock"]
    expected_revision_id: UUID
    target: Target
    source: MessageSource
    reason: Reason


RevisionTransitionRequest = Annotated[
    EditRevisionRequest | ConfirmRevisionRequest | LockRevisionRequest | UnlockRevisionRequest,
    Field(discriminator="action"),
]


class EvaluateRequest(ApiModel):
    knowledge_facts: tuple[AvailableKnowledgeFact, ...] = ()
    proposed_update: ProposedDomainUpdate | None = None


class EvaluationResponse(ApiModel):
    revision_id: UUID
    decision: AskDecision | DeriveDecision | AssumeDecision | BlockDecision | ReadyDecision
    rendered_question: RenderedQuestion | None = None


class RevisionListResponse(ApiModel):
    revisions: tuple[DesignRevision, ...]
