"""Internal conversational adapter boundary; drafts carry no State authority.

No provider, route, persistence contract or catalog activation is selected here.
The caller supplies the actual committed revision and an already verified release.
Canonical State and source Parser evidence are separate immutable context strings;
the adapter cannot mutate either through a shared ORM object or nested dictionary.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from jewelai_domain.knowledge_runtime import (
    AnyActiveKnowledge,
    KnowledgeReleaseBinding,
    validate_active_knowledge,
)
from jewelai_domain.models_v1_1 import AnyDesignRevision, validate_design_revision
from jewelai_parser import parse_full_message

if TYPE_CHECKING:
    from .semantic_proposal import SemanticProposal


@dataclass(frozen=True)
class ConversationContext:
    message_id: UUID
    original_text: str
    locale: str
    role_id: str
    committed_revision_json: str
    source_parse_json: str
    knowledge_binding_json: str
    # US-01 supplies scoped, verified data; defaults preserve the original internal adapter.
    turn_binding_json: str = "{}"
    semantic_evidence_json: str = "{}"
    safe_reply_options_json: str = "[]"


@dataclass(frozen=True)
class UntrustedConversationDraft:
    """Requires server-side claim validation before any future storage or delivery."""

    text: str
    provider: str
    model: str
    prompt_version: str


class ConversationModel(Protocol):
    def interpret(self, context: ConversationContext) -> "SemanticProposal":
        """Primary interpretation; no Parser-derived meaning or State write."""
        ...

    def draft_reply(self, context: ConversationContext) -> UntrustedConversationDraft:
        """No State write, arbitrary tool execution or implicit provider authorization."""
        ...


def build_conversation_context(
    *,
    message_id: UUID,
    original_text: str,
    locale: str,
    role_id: str,
    committed_revision: AnyDesignRevision,
    dictionary,
    active_runtime: AnyActiveKnowledge,
    release_binding: KnowledgeReleaseBinding,
) -> ConversationContext:
    """Reuse current Parser and verified identities; never promote recognized terms.

    This internal builder does not prove that a revision was committed: its caller
    must obtain that revision from the scoped repository after commit. Likewise,
    runtime/binding must come from the existing verified store, not a model draft.
    """
    revision = validate_design_revision(committed_revision)
    active = validate_active_knowledge(active_runtime)
    binding = KnowledgeReleaseBinding.model_validate(release_binding)
    if active.contract_version != "1.1.0" or binding.knowledge_contract_version != "1.1.0":
        raise ValueError("New conversational context requires Knowledge contract 1.1.0")
    if binding.release_identity != (
        active.package_id,
        str(active.artifact_version),
        active.runtime_sha256,
        active.validation_report_sha256,
    ):
        raise ValueError("Conversational context Knowledge identity mismatch")
    parsed = parse_full_message(
        original_text,
        locale=locale,
        dictionary=dictionary,
        knowledge_runtime=active.compiled_runtime,
    )
    return ConversationContext(
        message_id=message_id,
        original_text=original_text,
        locale=locale,
        role_id=role_id,
        committed_revision_json=revision.model_dump_json(),
        source_parse_json=parsed.model_dump_json(),
        knowledge_binding_json=binding.model_dump_json(),
    )
