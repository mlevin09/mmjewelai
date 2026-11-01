"""Internal parsed-evidence to verified enrichment orchestration.

This module is intentionally not connected to an HTTP route. It composes existing boundaries
without making parser or prompt packages depend on one another.
"""

from enum import StrEnum

from jewelai_domain.dictionary import DictionaryLocale, DictionaryRegistry, UnsupportedMatch
from jewelai_domain.knowledge_policy import RuntimeProvenance, RuntimeSemanticState
from jewelai_domain.knowledge_runtime import (
    AnyActiveKnowledge,
    AnyKnowledgeStore,
    AnyValidationReport,
)
from jewelai_domain.models import Explicit, ImmutableModel, KnownValue, MessageSource
from jewelai_domain.models_v1_1 import (
    AnyDesignRevision,
    CompositionV1_1,
    DesignV1_1,
    validate_design_revision,
)
from jewelai_parser import (
    AnyParserProposal,
    CandidateApplication,
    CandidateCertainty,
    CandidateClassification,
    CandidateSubject,
    CandidateUpdate,
    FullMessageParseResult,
    NormalizationSource,
    ParserCandidate,
    ParserIssueCode,
    ParserTarget,
    StructuredCandidate,
    StructuredTarget,
    build_parser_proposal,
)
from jewelai_parser.models import QuantityCandidate, StyleTermsCandidate, TermCandidate
from jewelai_parser.p010_symmetry import TARGET as SYMMETRY_TARGET
from jewelai_parser.p010_symmetry import VALUE as SYMMETRY_VALUE
from jewelai_parser.p010_symmetry import verified_symmetry_candidate
from jewelai_prompts import (
    AnyPromptEnrichmentResult,
    EnrichmentDecision,
    EnrichmentProposal,
    ParametricEnrichmentReference,
    PromptTemplateBundle,
    enrich_prompt_with_active_release,
)
from pydantic import BaseModel, model_validator


class ParsedEnrichmentReleaseMismatchError(ValueError):
    """Raised when parse evidence and the explicitly selected ACTIVE release differ."""


class ParsedEnrichmentInputError(ValueError):
    """Raised when versioned parser inputs cannot be combined safely."""


class ParseKnowledgeLineage(StrEnum):
    MATCHED_VERIFIED_RELEASE = "matched_verified_release"
    ABSENT = "absent"


class CandidateDispositionOutcome(StrEnum):
    APPLIED = "APPLIED"
    KEPT = "KEPT"
    BLOCKED = "BLOCKED"
    DEFERRED = "DEFERRED"
    NO_CHANGE = "NO_CHANGE"


class CandidateDispositionReason(StrEnum):
    MATRIX_EVALUATED = "matrix_evaluated"
    PARSER_REJECTED = "parser_rejected"
    ALREADY_CURRENT = "already_current"
    AMBIGUOUS_CANDIDATE = "ambiguous_candidate"
    UNRESOLVED_CANDIDATE = "unresolved_candidate"
    PREFERENCE_REQUIRES_ACCEPTANCE = "preference_requires_acceptance"
    PROHIBITION_RETAINED = "prohibition_retained"
    PRESERVATION_RETAINED = "preservation_retained"
    SIDE_STONE_GROUP_MISSING = "side_stone_group_missing"
    SIDE_STONE_GROUP_AMBIGUOUS = "side_stone_group_ambiguous"
    TARGET_NOT_SUPPORTED_BY_PARSER = "target_not_supported_by_parser"
    COMPONENT_TARGET_NOT_REPRESENTABLE = "component_target_not_representable"
    DUPLICATE_TARGET_CANDIDATES = "duplicate_target_candidates"


class CandidateDisposition(ImmutableModel):
    candidate: StructuredCandidate
    outcome: CandidateDispositionOutcome
    reason: CandidateDispositionReason
    concrete_target: str | None = None
    parser_issue_codes: tuple[ParserIssueCode, ...] = ()
    enrichment_proposal: EnrichmentProposal | None = None
    enrichment_decision: EnrichmentDecision | None = None

    @model_validator(mode="after")
    def validate_evaluation_lineage(self):
        if self.enrichment_decision is not None:
            if self.enrichment_proposal is None:
                raise ValueError("an enrichment decision requires its proposal")
            if self.enrichment_decision.proposal != self.enrichment_proposal:
                raise ValueError("candidate disposition proposal/decision mismatch")
            if self.outcome.value != self.enrichment_decision.outcome:
                raise ValueError("candidate disposition outcome/decision mismatch")
        if self.outcome in {
            CandidateDispositionOutcome.DEFERRED,
            CandidateDispositionOutcome.NO_CHANGE,
        } and (self.enrichment_proposal is not None or self.enrichment_decision is not None):
            raise ValueError("unevaluated disposition cannot contain enrichment evaluation")
        return self


class ParsedCandidateEnrichmentResult(ImmutableModel):
    parse_result: FullMessageParseResult
    parse_knowledge_lineage: ParseKnowledgeLineage
    parser_proposal: AnyParserProposal
    dispositions: tuple[CandidateDisposition, ...]
    enrichment_result: AnyPromptEnrichmentResult

    @model_validator(mode="after")
    def validate_complete_lineage(self):
        candidate_ids = tuple(item.candidate_id for item in self.parse_result.candidates)
        disposition_ids = tuple(item.candidate.candidate_id for item in self.dispositions)
        if candidate_ids != disposition_ids:
            raise ValueError("every parsed candidate requires one disposition in source order")
        if self.enrichment_result.design_revision_id != str(
            self.parser_proposal.expected_revision_id
        ):
            raise ValueError("parser and enrichment revision lineage mismatch")
        return self


def enrich_parsed_candidates_with_active_release(
    revision: AnyDesignRevision | object,
    *,
    parse_result: FullMessageParseResult,
    source: MessageSource,
    dictionary: DictionaryRegistry,
    templates: PromptTemplateBundle,
    artifact_store: AnyKnowledgeStore,
    knowledge_package_id: str,
    knowledge_artifact_version: str,
    active_release: AnyActiveKnowledge | object,
    validation_report: AnyValidationReport | object,
    parametric_catalog_id: str | None = None,
    parametric_artifact_version: str | None = None,
    parametric_catalog_sha256: str | None = None,
    parametric_references: tuple[ParametricEnrichmentReference, ...] = (),
    template_id: str = "jewelry_visualization",
) -> ParsedCandidateEnrichmentResult:
    """Evaluate safe parsed candidates without mutating the authoritative revision."""

    revision = validate_design_revision(revision)
    parsed = FullMessageParseResult.model_validate(parse_result)
    source = MessageSource.model_validate(source)
    templates = PromptTemplateBundle.model_validate(templates)

    if parsed.dictionary_artifact_version != dictionary.artifact_version:
        raise ParsedEnrichmentInputError(
            "parsed evidence dictionary version does not match the supplied dictionary"
        )
    candidate_ids = tuple(item.candidate_id for item in parsed.candidates)
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ParsedEnrichmentInputError("parsed evidence candidate IDs must be unique")

    verified = artifact_store.load_active_runtime(
        knowledge_package_id,
        knowledge_artifact_version,
        active_release=active_release,
        validation_report=validation_report,
    )
    parse_lineage = _verify_parse_release(parsed, verified)

    prepared: dict[str, CandidateUpdate] = {}
    symmetry_candidates: list[StructuredCandidate] = []
    dispositions: dict[str, CandidateDisposition] = {}
    group_ids = tuple(sorted(group.group_id for group in revision.design.side_stones))

    for candidate in parsed.candidates:
        update, deferred = _prepare_candidate(
            candidate,
            group_ids,
            dictionary=dictionary,
            locale=parsed.requested_locale,
        )
        if deferred is not None:
            if (
                revision.schema_version == "1.1.0"
                and parse_lineage == ParseKnowledgeLineage.MATCHED_VERIFIED_RELEASE
                and deferred.reason == CandidateDispositionReason.TARGET_NOT_SUPPORTED_BY_PARSER
                and candidate.semantic_subject == SYMMETRY_TARGET
                and candidate.normalization_source == NormalizationSource.KNOWLEDGE_LIBRARY
                and verified_symmetry_candidate(
                    candidate, parsed, verified.compiled_runtime, dictionary=dictionary
                )
            ):
                symmetry_candidates.append(candidate)
            else:
                dispositions[candidate.candidate_id] = deferred
        elif update is not None:
            prepared[candidate.candidate_id] = update

    by_target: dict[str, list[str]] = {}
    for candidate_id, update in prepared.items():
        by_target.setdefault(update.concrete_target, []).append(candidate_id)
    for target, candidate_ids in by_target.items():
        if len(candidate_ids) < 2:
            continue
        for candidate_id in candidate_ids:
            candidate = _candidate_by_id(parsed, candidate_id)
            dispositions[candidate_id] = CandidateDisposition(
                candidate=candidate,
                outcome=CandidateDispositionOutcome.DEFERRED,
                reason=CandidateDispositionReason.DUPLICATE_TARGET_CANDIDATES,
                concrete_target=target,
            )
            prepared.pop(candidate_id)

    candidate_for_target = {
        update.concrete_target: _candidate_by_id(parsed, candidate_id)
        for candidate_id, update in prepared.items()
    }
    parser_candidate = ParserCandidate(
        updates=tuple(
            update
            for _, update in sorted(
                prepared.items(),
                key=lambda item: (item[1].concrete_target, item[0]),
            )
        )
    )
    parser_proposal = build_parser_proposal(
        revision,
        expected_revision_id=revision.revision_id,
        source=source,
        locale=parsed.requested_locale,
        dictionary=dictionary,
        candidate=parser_candidate,
    )
    parser_proposal = _retain_source_normalization(
        parser_proposal, revision, candidate_for_target, dictionary
    )

    issues_by_target: dict[str, list[ParserIssueCode]] = {}
    for issue in parser_proposal.issues:
        issues_by_target.setdefault(issue.concrete_target, []).append(issue.code)
    accepted_by_target = {
        accepted.concrete_target: accepted for accepted in parser_proposal.accepted_updates
    }

    proposals = []
    # Existing evidence and EnrichmentProposal contracts already admit this
    # approved binding. Do not forge a legacy ParserTarget/AcceptedUpdate.
    if len(symmetry_candidates) == 1:
        candidate = symmetry_candidates[0]
        target = SYMMETRY_TARGET
        value = SYMMETRY_VALUE
        if not isinstance(revision.design.composition, KnownValue):
            # A missing aggregate has no addressable child yet. Use the existing
            # complete aggregate operation, containing ONLY the user-stated leaf.
            # Canonical v2 checks the real parent (including N/A/LOCK/precedence).
            # Do not preseed a fabricated revision to make a child guard succeed.
            target = "composition"
            value = CompositionV1_1(
                symmetry_mode=Explicit[str](value=SYMMETRY_VALUE, source=source)
            ).model_dump(mode="json")
        proposals.append(
            EnrichmentProposal(
                target=target,
                semantic_state=RuntimeSemanticState.NORMALIZED,
                provenance=RuntimeProvenance.NORMALIZED_FROM_USER,
                value=value,
                source_id=candidate.candidate_id,
            )
        )
    else:
        for candidate in symmetry_candidates:
            dispositions[candidate.candidate_id] = CandidateDisposition(
                candidate=candidate,
                outcome=CandidateDispositionOutcome.DEFERRED,
                reason=CandidateDispositionReason.DUPLICATE_TARGET_CANDIDATES,
                concrete_target=SYMMETRY_TARGET,
            )
    for target, candidate in candidate_for_target.items():
        issues = tuple(sorted(issues_by_target.get(target, ()), key=lambda item: item.value))
        if issues:
            dispositions[candidate.candidate_id] = CandidateDisposition(
                candidate=candidate,
                outcome=CandidateDispositionOutcome.BLOCKED,
                reason=CandidateDispositionReason.PARSER_REJECTED,
                concrete_target=target,
                parser_issue_codes=issues,
            )
            continue
        accepted = accepted_by_target.get(target)
        if accepted is None:
            dispositions[candidate.candidate_id] = CandidateDisposition(
                candidate=candidate,
                outcome=CandidateDispositionOutcome.NO_CHANGE,
                reason=CandidateDispositionReason.ALREADY_CURRENT,
                concrete_target=target,
            )
            continue
        normalized = accepted.match_kind is not None
        proposal = EnrichmentProposal(
            target=accepted.concrete_target,
            semantic_state=(
                RuntimeSemanticState.NORMALIZED if normalized else RuntimeSemanticState.EXPLICIT
            ),
            provenance=(
                RuntimeProvenance.NORMALIZED_FROM_USER
                if normalized
                else RuntimeProvenance.USER_EXPLICIT_LATEST
            ),
            value=_json_value(accepted.canonical_value),
            source_id=candidate.candidate_id,
        )
        proposals.append(proposal)

    enrichment_result = enrich_prompt_with_active_release(
        revision,
        templates,
        artifact_store,
        knowledge_package_id=knowledge_package_id,
        knowledge_artifact_version=knowledge_artifact_version,
        active_release=active_release,
        validation_report=validation_report,
        proposals=tuple(proposals),
        parametric_catalog_id=parametric_catalog_id,
        parametric_artifact_version=parametric_artifact_version,
        parametric_catalog_sha256=parametric_catalog_sha256,
        parametric_references=parametric_references,
        template_id=template_id,
    )
    decisions = {item.proposal.source_id: item for item in enrichment_result.decisions}
    proposal_by_source = {item.source_id: item for item in proposals}
    for candidate_id, proposal in proposal_by_source.items():
        decision = decisions[candidate_id]
        candidate = _candidate_by_id(parsed, candidate_id)
        dispositions[candidate_id] = CandidateDisposition(
            candidate=candidate,
            outcome=CandidateDispositionOutcome(decision.outcome),
            reason=CandidateDispositionReason.MATRIX_EVALUATED,
            concrete_target=proposal.target,
            enrichment_proposal=proposal,
            enrichment_decision=decision,
        )

    return ParsedCandidateEnrichmentResult(
        parse_result=parsed,
        parse_knowledge_lineage=parse_lineage,
        parser_proposal=parser_proposal,
        dispositions=tuple(dispositions[item.candidate_id] for item in parsed.candidates),
        enrichment_result=enrichment_result,
    )


def _retain_source_normalization(proposal, revision, candidates, dictionary):
    """Retain alias evidence lost by the existing cross-locale value projection.

    Reuse ParserProposal normalization in the source language. Only replace
    accepted-input metadata when it proves the SAME canonical target/value;
    never replace the proposed design, issues, authority or application result.
    """
    accepted = {u.concrete_target: u for u in proposal.accepted_updates}
    warnings = list(proposal.warnings)
    issue_targets = {i.concrete_target for i in proposal.issues}
    locales = (proposal.locale, "ru" if proposal.locale == "en" else "en")
    for target, candidate in candidates.items():
        original = candidate.parser_update
        update = accepted.get(target)
        if (
            original is not None
            and candidate.normalization_source == NormalizationSource.DOMAIN_DICTIONARY
            and target not in issue_targets
            and (update is None or original.value != update.candidate_value)
        ):
            for locale in locales:
                original_proposal = build_parser_proposal(
                    revision,
                    expected_revision_id=proposal.expected_revision_id,
                    source=proposal.source,
                    locale=locale,
                    dictionary=dictionary,
                    candidate=ParserCandidate(updates=(original,)),
                )
                if original_proposal.issues:
                    continue
                if update is not None:
                    if len(original_proposal.accepted_updates) != 1:
                        continue
                    original_update = original_proposal.accepted_updates[0]
                    if original_update.canonical_value != update.canonical_value:
                        continue
                    accepted[target] = original_update
                elif original_proposal.accepted_updates:
                    # Only retain no-change warnings when BOTH normalizations
                    # leave this target unchanged. Never introduce an update.
                    continue
                warnings = [w for w in warnings if w.concrete_target != target]
                warnings.extend(original_proposal.warnings)
                break
    return proposal.model_copy(
        update={
            "accepted_updates": tuple(
                accepted[u.concrete_target] for u in proposal.accepted_updates
            ),
            "warnings": tuple(
                sorted(warnings, key=lambda w: (w.concrete_target, w.normalized_input))
            ),
        }
    )


def _verify_parse_release(
    parsed: FullMessageParseResult,
    verified: AnyActiveKnowledge,
) -> ParseKnowledgeLineage:
    if parsed.knowledge_package_id is None:
        return ParseKnowledgeLineage.ABSENT
    actual = (
        parsed.knowledge_package_id,
        parsed.knowledge_artifact_version,
        parsed.knowledge_runtime_sha256,
    )
    expected = (
        verified.package_id,
        str(verified.artifact_version),
        verified.runtime_sha256,
    )
    if actual != expected:
        raise ParsedEnrichmentReleaseMismatchError(
            "parsed evidence does not match the explicitly selected verified Knowledge release"
        )
    return ParseKnowledgeLineage.MATCHED_VERIFIED_RELEASE


def proposed_design_for_transition(revision, evaluation):
    """Combine legacy parser edits and the bounded, Matrix-approved C2 delta.

    This is an internal consumer of existing proposals, not a new durable DTO.
    The caller still owns revise_design, source authorization and database CAS.
    """
    revision = validate_design_revision(revision)
    if str(revision.revision_id) != evaluation.enrichment_result.design_revision_id:
        raise ParsedEnrichmentInputError("enrichment transition revision mismatch")
    design = evaluation.parser_proposal.proposed_design
    if revision.schema_version != "1.1.0":
        return design
    for disposition in evaluation.dispositions:
        decision = disposition.enrichment_decision
        if not (
            decision is not None
            and decision.target in {SYMMETRY_TARGET, "composition"}
            and decision.outcome == "APPLIED"
            and disposition.candidate.semantic_subject == SYMMETRY_TARGET
            and disposition.candidate.normalization_source == NormalizationSource.KNOWLEDGE_LIBRARY
        ):
            continue
        if decision.target == "composition":
            proposed = CompositionV1_1.model_validate(decision.result.value)
            if (
                not isinstance(proposed.symmetry_mode, KnownValue)
                or proposed.symmetry_mode.value != SYMMETRY_VALUE
            ):
                raise ParsedEnrichmentInputError("invalid approved symmetry aggregate")
        elif decision.result.value != SYMMETRY_VALUE:
            raise ParsedEnrichmentInputError("invalid approved symmetry value")
        current = revision.design.composition
        child = current.value.symmetry_mode if isinstance(current, KnownValue) else None
        if isinstance(child, KnownValue) and child.value == SYMMETRY_VALUE:
            continue
        payload = design.model_dump(mode="json")
        value = Explicit[str](value=SYMMETRY_VALUE, source=evaluation.parser_proposal.source)
        if isinstance(current, KnownValue):
            payload["composition"]["value"]["symmetry_mode"] = value.model_dump(mode="json")
        else:
            payload["composition"] = Explicit[dict](
                value={"symmetry_mode": value.model_dump(mode="json")},
                source=evaluation.parser_proposal.source,
            ).model_dump(mode="json")
        design = DesignV1_1.model_validate(payload)
    return design


def _prepare_candidate(
    candidate: StructuredCandidate,
    group_ids: tuple[str, ...],
    *,
    dictionary: DictionaryRegistry,
    locale: str,
) -> tuple[CandidateUpdate | None, CandidateDisposition | None]:
    common = {"candidate": candidate, "outcome": CandidateDispositionOutcome.DEFERRED}
    if candidate.classification == CandidateClassification.PROHIBITION:
        return None, CandidateDisposition(
            **common,
            reason=CandidateDispositionReason.PROHIBITION_RETAINED,
        )
    if candidate.classification == CandidateClassification.PRESERVATION:
        return None, CandidateDisposition(
            **common,
            reason=CandidateDispositionReason.PRESERVATION_RETAINED,
        )
    if candidate.certainty == CandidateCertainty.AMBIGUOUS:
        return None, CandidateDisposition(
            **common,
            reason=CandidateDispositionReason.AMBIGUOUS_CANDIDATE,
        )
    if candidate.certainty == CandidateCertainty.UNRESOLVED:
        return None, CandidateDisposition(
            **common,
            reason=CandidateDispositionReason.UNRESOLVED_CANDIDATE,
        )
    if candidate.classification == CandidateClassification.PREFERENCE:
        return None, CandidateDisposition(
            **common,
            reason=CandidateDispositionReason.PREFERENCE_REQUIRES_ACCEPTANCE,
        )
    if candidate.subject != CandidateSubject.PRODUCT_BODY and candidate.target in {
        StructuredTarget.METAL_MATERIAL,
        StructuredTarget.METAL_COLOR,
    }:
        return None, CandidateDisposition(
            **common,
            reason=CandidateDispositionReason.COMPONENT_TARGET_NOT_REPRESENTABLE,
        )
    if (
        candidate.target == StructuredTarget.STYLE
        and candidate.subject != CandidateSubject.OVERALL_DESIGN
    ):
        return None, CandidateDisposition(
            **common, reason=CandidateDispositionReason.COMPONENT_TARGET_NOT_REPRESENTABLE
        )
    if candidate.target is None and candidate.subject in {
        CandidateSubject.PRONGS,
        CandidateSubject.BAND,
    }:
        return None, CandidateDisposition(
            **common, reason=CandidateDispositionReason.COMPONENT_TARGET_NOT_REPRESENTABLE
        )
    if candidate.application == CandidateApplication.PARSER_CANDIDATE_READY:
        update = candidate.parser_update
        if (
            update is not None
            and candidate.normalization_source == NormalizationSource.DOMAIN_DICTIONARY
            and len(candidate.normalized_values) == 1
        ):
            entry = dictionary[candidate.normalized_values[0]]
            localized_term = entry.canonical_terms.for_locale(DictionaryLocale(locale))
            if isinstance(update.value, TermCandidate) and isinstance(
                dictionary.normalize(
                    update.value.text,
                    locale=locale,
                    category=entry.category,
                ),
                UnsupportedMatch,
            ):
                update = update.model_copy(update={"value": TermCandidate(text=localized_term)})
            elif isinstance(update.value, StyleTermsCandidate) and all(
                isinstance(
                    dictionary.normalize(term, locale=locale, category=entry.category),
                    UnsupportedMatch,
                )
                for term in update.value.terms
            ):
                update = update.model_copy(
                    update={"value": StyleTermsCandidate(terms=(localized_term,))}
                )
        return update, None

    if candidate.target in {
        StructuredTarget.SIDE_STONE_MATERIAL,
        StructuredTarget.SIDE_STONE_SHAPE,
        StructuredTarget.SIDE_STONE_CUT,
        StructuredTarget.SIDE_STONE_WEIGHT,
        StructuredTarget.SIDE_STONE_DIMENSIONS,
        StructuredTarget.SIDE_STONE_SETTING,
        StructuredTarget.SIDE_STONE_QUANTITY,
    }:
        if not group_ids:
            return None, CandidateDisposition(
                **common,
                reason=CandidateDispositionReason.SIDE_STONE_GROUP_MISSING,
            )
        if len(group_ids) > 1:
            return None, CandidateDisposition(
                **common,
                reason=CandidateDispositionReason.SIDE_STONE_GROUP_AMBIGUOUS,
            )
        if candidate.target == StructuredTarget.SIDE_STONE_QUANTITY:
            return (
                CandidateUpdate(
                    target=ParserTarget.SIDE_STONE_QUANTITY,
                    group_id=group_ids[0],
                    value=QuantityCandidate.model_validate({"value": candidate.raw_value}),
                ),
                None,
            )

    return None, CandidateDisposition(
        **common,
        reason=CandidateDispositionReason.TARGET_NOT_SUPPORTED_BY_PARSER,
    )


def _candidate_by_id(parsed: FullMessageParseResult, candidate_id: str) -> StructuredCandidate:
    return next(item for item in parsed.candidates if item.candidate_id == candidate_id)


def _json_value(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value
