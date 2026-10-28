"""Neutral preparation command/summary, never client-supplied authority."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from jewelai_domain.models import ImmutableModel
from jewelai_prompts import FinalPromptReadiness
from jewelai_prompts.models import Sha256
from pydantic import Field, StrictInt


class GenerationPreparationRequest(ImmutableModel):
    schema_version: Literal["1.0.0"]
    expected_revision_id: UUID
    expected_enrichment_cycle_id: UUID
    expected_enrichment_cycle_number: Annotated[StrictInt, Field(ge=1)]
    expected_enrichment_result_hash: Sha256
    expected_handoff_hash: Sha256
    expected_clarification_plan_hash: Sha256
    expected_decision_frontier_hash: Sha256


class GenerationPreparationSummary(ImmutableModel):
    schema_version: Literal["1.0.0"]
    preparation_id: UUID
    session_id: UUID
    product_state_revision_id: UUID
    enrichment_cycle_id: UUID
    enrichment_cycle_number: int
    source_handoff_hash: Sha256
    artifact_hash: Sha256
    rendering_hash: Sha256
    readiness: FinalPromptReadiness
    unresolved_summary: tuple[str, ...]
    created_at: datetime
