"""Read-only HTTP surface for Knowledge Library Contract 2.0 (ADR 0048, Architecture v1.2 §8).

The Semantic Orchestrator calls ``KnowledgeApi`` in-process. These endpoints exist for callers
outside the backend process (for example a separately deployed consultant or trainer).

- Disabled unless ``KNOWLEDGE_KB_HTTP_ENABLED=true``; enabling it is a deployment decision.
- Every request needs the existing bearer authentication.
- The ``kb`` caller identity is fixed by server configuration (``KNOWLEDGE_KB_HTTP_CALLER``,
  default ``consultant``); a client can never choose it, so it cannot claim the SO's purposes.
- Every operation is a READ ONLY transaction through ``KnowledgeApi``. No endpoint writes.
"""

import os
from dataclasses import asdict, dataclass
from typing import Annotated, Any

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from jewelai_domain.kb_contract import KnowledgeKbError
from jewelai_persistence.knowledge_kb import KnowledgeApi
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

ERROR_STATUS = {
    "unknown_entity": 404,
    "no_data": 404,
    "release_not_found": 404,
    "release_unavailable": 410,
    "purpose_not_allowed": 403,
    "ambiguous_term": 409,
    "scope_conflict": 409,
    "evidence_conflict": 409,
    "payload_conflict": 409,
}


@dataclass(frozen=True)
class KnowledgeHttpConfig:
    enabled: bool = False
    caller_id: str = "consultant"

    @classmethod
    def from_environment(cls) -> "KnowledgeHttpConfig":
        enabled = os.getenv("KNOWLEDGE_KB_HTTP_ENABLED", "false").strip().lower()
        if enabled not in ("true", "false"):
            raise ValueError("KNOWLEDGE_KB_HTTP_ENABLED must be true or false")
        caller = os.getenv("KNOWLEDGE_KB_HTTP_CALLER", "consultant").strip()
        if not caller:
            raise ValueError("KNOWLEDGE_KB_HTTP_CALLER must not be empty")
        return cls(enabled=enabled == "true", caller_id=caller)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluateClaimRequest(_Strict):
    entity_id: str = Field(min_length=1, max_length=160)
    attribute_id: str = Field(min_length=1, max_length=80)
    value: dict[str, Any]
    scope: dict[str, Any] = Field(default_factory=dict)
    value_kind: str = "exact"


class EvaluateRulesRequest(_Strict):
    spec: dict[str, Any]
    purpose: str = "validate_warn"
    preview: bool = True


def _scope(items: list[str] | None) -> dict[str, str]:
    scope: dict[str, str] = {}
    for item in items or ():
        key, separator, value = item.partition(":")
        if not separator or not key or not value:
            raise ValueError(f"scope must be key:value, got {item!r}")
        scope[key] = value
    return scope


def register_knowledge_routes(
    app: FastAPI,
    authenticated: Any,
    session_factory: sessionmaker[Session],
    config: KnowledgeHttpConfig,
) -> None:
    """Attach /knowledge routes. ``authenticated`` is the app's bearer dependency."""
    api = KnowledgeApi(session_factory, config.caller_id)

    def run(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except KnowledgeKbError as error:
            return JSONResponse(
                status_code=ERROR_STATUS[error.code],
                content={"error": error.code, "detail": error.detail},
            )
        except ValueError as error:
            return JSONResponse(
                status_code=422, content={"error": "invalid_request", "detail": str(error)}
            )

    def as_json(result):
        if isinstance(result, JSONResponse):
            return result
        if isinstance(result, tuple):
            return [
                asdict(item) if hasattr(item, "__dataclass_fields__") else item for item in result
            ]
        return asdict(result) if hasattr(result, "__dataclass_fields__") else result

    @app.get("/knowledge/releases/{release_id}")
    def knowledge_release(release_id: str, _: authenticated):
        # "active" is accepted only here, for the first pin (v1.2 §8).
        return as_json(run(api.get_release, release_id))

    @app.get("/knowledge/releases/{release_id}/terms")
    def knowledge_terms(
        release_id: str,
        _: authenticated,
        text: Annotated[str, Query(min_length=1, max_length=200)],
        lang: Annotated[str | None, Query(pattern="^(ru|en)$")] = None,
    ):
        return as_json(run(api.resolve_terms, text, release_id, lang=lang))

    @app.get("/knowledge/releases/{release_id}/entities/{entity_id}/claims")
    def knowledge_claims(
        release_id: str,
        entity_id: str,
        _: authenticated,
        purpose: Annotated[str, Query(min_length=1, max_length=32)],
        attribute: Annotated[list[str] | None, Query()] = None,
        scope: Annotated[list[str] | None, Query()] = None,
    ):
        def call():
            return api.get_claims(
                entity_id, purpose, release_id, attributes=attribute, scope=_scope(scope)
            )

        return as_json(run(call))

    @app.post("/knowledge/releases/{release_id}/evaluate-claim")
    def knowledge_evaluate_claim(release_id: str, body: EvaluateClaimRequest, _: authenticated):
        def call():
            return api.evaluate_claim(
                body.entity_id,
                body.attribute_id,
                body.value,
                release_id,
                scope=body.scope,
                value_kind=body.value_kind,
            )

        return as_json(run(call))

    @app.post("/knowledge/releases/{release_id}/evaluate-rules")
    def knowledge_evaluate_rules(release_id: str, body: EvaluateRulesRequest, _: authenticated):
        def call():
            return api.evaluate_rules(
                body.spec, release_id, purpose=body.purpose, preview=body.preview
            )

        return as_json(run(call))

    @app.get("/knowledge/releases/{release_id}/search")
    def knowledge_search(
        release_id: str,
        _: authenticated,
        q: Annotated[str, Query(min_length=1, max_length=200)],
        purpose: Annotated[str, Query(pattern="^(search|explain)$")] = "search",
    ):
        return as_json(run(api.search_knowledge, q, release_id, purpose=purpose))
