"""Provider-neutral Parser Proposal v1."""

from .knowledge_matcher import (
    AmbiguousKnowledgeMatch,
    KnowledgeLibraryMatcher,
    KnowledgeMatchCandidate,
    KnowledgeMatchMethod,
    ResolvedKnowledgeMatch,
    UnsupportedKnowledgeMatch,
    normalize_knowledge_text,
    ru_morphology_key,
)
from .models import (
    PARSER_SCHEMA_VERSION,
    AcceptedUpdate,
    CandidateUpdate,
    DimensionsScaleCandidate,
    ParserCandidate,
    ParserIssue,
    ParserIssueCode,
    ParserProposal,
    ParserTarget,
    ParserWarning,
    ParserWarningCode,
)
from .proposals import StaleParserProposalError, build_parser_proposal

__all__ = [
    "PARSER_SCHEMA_VERSION",
    "AcceptedUpdate",
    "AmbiguousKnowledgeMatch",
    "CandidateUpdate",
    "DimensionsScaleCandidate",
    "KnowledgeLibraryMatcher",
    "KnowledgeMatchCandidate",
    "KnowledgeMatchMethod",
    "ParserCandidate",
    "ParserIssue",
    "ParserIssueCode",
    "ParserProposal",
    "ParserTarget",
    "ParserWarning",
    "ParserWarningCode",
    "ResolvedKnowledgeMatch",
    "StaleParserProposalError",
    "UnsupportedKnowledgeMatch",
    "build_parser_proposal",
    "normalize_knowledge_text",
    "ru_morphology_key",
]
