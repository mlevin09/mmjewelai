"""F04 dispatch for the existing session runtime, revision and atomic repository paths.

Creation defaults remain L. Only trusted retained Q2/R2 pins select this module.
No provider, new canonical store or parallel parsing/planning engine is introduced.
"""

import hashlib
from datetime import UTC
from functools import wraps
from types import SimpleNamespace
from uuid import UUID

from jewelai_domain.clarification_state import F04_PROFILE, EvidenceScope, evidence_hash
from jewelai_domain.dictionary import DictionaryCategory, EntryLifecycle
from jewelai_domain.knowledge_runtime import bind_verified_release, knowledge_store_version
from jewelai_domain.knowledge_storage import KnowledgeArtifactStorageError
from jewelai_domain.models import KnownValue, MessageSource
from jewelai_domain.revisions import RevisionConflict, revise_design
from jewelai_parser import ParserTarget, parse_full_message, same_parse_evidence
from jewelai_parser.full_message import _parse_recorded_message, _source_governance
from jewelai_persistence import (
    ClarificationDecisionConflictError,
    ClarificationDecisionIntegrityError,
    ClarificationPlanIntegrityError,
    EnrichmentCycleConflictError,
    EnrichmentIntegrityError,
    KnowledgeReleasePinConflictError,
    NotFoundError,
    OwnershipMismatchError,
    StaleRevisionError,
    UserCorrectionConflictError,
    UserCorrectionIntegrityError,
)
from jewelai_prompts import (
    FinalPromptArtifactVersions,
    KnowledgeReleaseReference,
    build_internal_final_prompt_handoff,
    enrich_prompt_with_active_release,
)
from jewelai_prompts.downstream_preparation import (
    DecisionFrontier,
    DecisionReference,
    preparation_hash,
)
from jewelai_prompts.downstream_preparation_v2 import PreparationGateEvidenceV2
from jewelai_prompts.final_prompt_v3 import FinalPromptSnapshotV2, assemble_internal_final_prompt_v3

from .clarification_answers import (
    ClarificationAnswerError,
    _parser_proposal,
    _resolve_decision,
)
from .clarification_v2 import (
    AcceptedResultTrigger,
    ClarificationAnswerResultV2,
    ClarificationPlanV2,
    InitialTrigger,
    ResumeRequest,
    ResumeResult,
    ResumeTrigger,
    decode_answer_result,
    seal_frontier,
)
from .conflict_evidence import product_body_material_conflict, stable_id
from .constraint_evidence import merge_constraint_evidence
from .correction_enrichment import (
    CorrectionReenrichmentResultV2,
    UserCorrection,
    decode_correction_result,
    process_user_correction,
)
from .f04_frontier import (
    accepted_target,
    advance_frontier,
    correction_accepted_targets,
    relevant_reoffers,
    resolving_assertions,
    validate_accepted_evidence,
)
from .f04_planning import (
    artifact_pins,
    f04_enrichment,
    f04_evaluation,
    input_context,
    plan_f04,
    protected_target,
    target_state,
)
from .parsed_enrichment import proposed_design_for_transition
from .prompt_enrichment_runtime import (
    InitialEnrichmentRequestV2,
    InitialEnrichmentRuntimeResultV2,
    PersistedClarificationAnswerRequestV2,
    PersistedUserCorrectionRequestV2,
    PromptEnrichmentRuntimeError,
    PromptEnrichmentWorkflowStateV2,
    _decision_lineage,
    _workflow_status,
)
from .prompt_enrichment_runtime import (
    PromptEnrichmentRuntimeErrorCode as Error,
)


def fail(code, detail):
    raise PromptEnrichmentRuntimeError(code, detail)


def boundary(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except PromptEnrichmentRuntimeError:
            raise
        except (NotFoundError, OwnershipMismatchError) as exc:
            raise PromptEnrichmentRuntimeError(
                Error.SESSION_NOT_FOUND,
                "Session, Message or plan was not found in organization scope",
            ) from exc
        except StaleRevisionError as exc:
            raise PromptEnrichmentRuntimeError(
                Error.STALE_REVISION, "Product State revision changed"
            ) from exc
        except (ClarificationDecisionConflictError, EnrichmentCycleConflictError) as exc:
            raise PromptEnrichmentRuntimeError(
                Error.CLARIFICATION_CONFLICT, "Clarification state changed before commit"
            ) from exc
        except UserCorrectionConflictError as exc:
            raise PromptEnrichmentRuntimeError(
                Error.CORRECTION_CONFLICT, "Correction source already has a durable result"
            ) from exc
        except (KnowledgeArtifactStorageError, KnowledgeReleasePinConflictError) as exc:
            raise PromptEnrichmentRuntimeError(
                Error.INVALID_KNOWLEDGE_RELEASE,
                "Pinned ACTIVE Knowledge release is unavailable or invalid",
            ) from exc
        except ClarificationAnswerError as exc:
            code = {
                "invalid_option": Error.INVALID_CLARIFICATION_OPTION,
                "invalid_decision": Error.INVALID_CLARIFICATION_DECISION,
            }.get(exc.code.value, Error.INVALID_CLARIFICATION_ANSWER)
            raise PromptEnrichmentRuntimeError(
                code, "Clarification decision failed deterministic validation"
            ) from exc
        except (
            ValueError,
            EnrichmentIntegrityError,
            ClarificationPlanIntegrityError,
            ClarificationDecisionIntegrityError,
            UserCorrectionIntegrityError,
        ) as exc:
            raise PromptEnrichmentRuntimeError(
                Error.INVALID_HISTORY, "F04 durable state failed integrity validation"
            ) from exc

    return guarded


def source_message(service, session_id, message_id, organization_id, *, repository=None):
    message = (repository or service.repository).get_message(
        session_id, message_id, organization_id
    )
    if message.actor != "user":
        fail(Error.INVALID_CLARIFICATION_ANSWER, "An original user Message is required")
    source = MessageSource(
        message_id=str(message.message_id),
        recorded_at=message.created_at.replace(tzinfo=UTC)
        if message.created_at.tzinfo is None
        else message.created_at,
    )
    return message, source


def answer_intent_hash(plan, question, request, message):
    return evidence_hash(
        dict(
            schema_version="2.0.0",
            contract_profile=F04_PROFILE,
            scope=plan.scope,
            source_plan_id=plan.plan_id,
            source_plan_hash=plan.content_hash,
            question_id=question.clarification_id,
            question_hash=evidence_hash(question),
            source_message_id=message.message_id,
            source_message_sha256=hashlib.sha256(message.content.encode("utf-8")).hexdigest(),
            expected_revision_id=request.expected_revision_id,
            decision=request.decision,
            selected_option=request.selected_option,
            selected_option_id=request.selected_option_id,
            release_pin=plan.cause_definitions[0].release_pin if plan.cause_definitions else None,
            artifact_pins=plan.artifact_pins,
        )
    )


@boundary
def start_initial_message(service, request):
    request = InitialEnrichmentRequestV2.model_validate(request)
    repo = service.repository
    session = repo.get_design_session(request.session_id, request.organization_id)
    if session.current_revision_id != request.expected_revision_id:
        fail(Error.STALE_REVISION, "Product State revision changed before initial enrichment")
    if any(
        (
            session.knowledge_package_id,
            session.knowledge_artifact_version,
            session.knowledge_runtime_sha256,
            session.knowledge_validation_report_sha256,
        )
    ):
        fail(
            Error.ENRICHMENT_CYCLE_MISMATCH,
            "Initial enrichment is only valid before the first cycle",
        )
    revision = repo.get_revision(
        request.session_id, request.expected_revision_id, request.organization_id
    )
    message, source = source_message(
        service, request.session_id, request.message_id, request.organization_id
    )
    verified = service._load_release()
    if knowledge_store_version(service.artifact_store) != "1.1.0":
        fail(
            Error.INVALID_KNOWLEDGE_RELEASE,
            "F enrichment requires the qualified Knowledge contract1.1",
        )
    binding = bind_verified_release(
        service.artifact_store,
        service.knowledge_package_id,
        service.knowledge_artifact_version,
        active_release=service.active_release,
        validation_report=service.validation_report,
    )
    scope = EvidenceScope(
        organization_id=request.organization_id,
        session_id=request.session_id,
        design_id=revision.design_id,
    )
    cycle_id, plan_id = service._uuid(), service._uuid()
    context = input_context(scope, revision, cycle_id, 1, service.artifacts, verified)
    parsed = parse_full_message(
        message.content,
        locale=session.locale,
        dictionary=service.artifacts.dictionary,
        knowledge_runtime=verified.compiled_runtime,
    )
    conflict = product_body_material_conflict(
        parsed,
        message=message,
        context=context,
        dictionary=service.artifacts.dictionary,
        knowledge_runtime=verified.compiled_runtime,
    )
    equivalent = (
        tuple(o.candidate_id for o in conflict.occurrences)
        if conflict and conflict.kind == "equivalent"
        else ()
    )
    first = service._evaluate(
        revision, parsed, source, **({"equivalent_candidate_ids": equivalent} if equivalent else {})
    )
    proposed = proposed_design_for_transition(revision, first)
    authoritative = revision
    if proposed != revision.design:
        authoritative = revise_design(
            revision,
            proposed,
            expected_revision_id=revision.revision_id,
            source=source,
            reason="Applied explicitly sourced F04 internal parsing",
            created_at=service._clock(),
        )
    post = (
        service._evaluate(
            authoritative,
            parsed,
            source,
            **({"equivalent_candidate_ids": equivalent} if equivalent else {}),
        )
        if authoritative != revision
        else first
    )
    evaluated = f04_evaluation(post, revision=authoritative, context=context)
    constraints = merge_constraint_evidence(
        post,
        session_id=request.session_id,
        organization_id=request.organization_id,
        source=source,
        authoritative_revision=authoritative,
        enrichment_cycle_id=cycle_id,
        _handled_candidate_ids=tuple(o.candidate_id for o in conflict.occurrences)
        if conflict and conflict.kind != "equivalent"
        else (),
    )
    plan = plan_f04(
        authoritative,
        evaluated,
        artifacts=service.artifacts,
        role_id=session.role_id,
        plan_id=plan_id,
        cycle_id=cycle_id,
        cycle_number=1,
        trigger=InitialTrigger(kind="initial", message_id=message.message_id),
        conflicts=(conflict,) if conflict else (),
        constraint_evidence=constraints,
    )
    return service._commit_verified(
        repo.commit_initial_enrichment,
        lambda bound, record: InitialEnrichmentRuntimeResultV2(
            parse_result=parsed,
            parser_proposal=first.parser_proposal,
            enrichment=evaluated,
            workflow=get_current_state(bound, request.session_id, request.organization_id),
        ),
        enrichment_cycle_id=cycle_id,
        session_id=request.session_id,
        organization_id=request.organization_id,
        expected_revision_id=revision.revision_id,
        resulting_revision=authoritative if authoritative != revision else None,
        result=evaluated.enrichment_result,
        created_at=service._clock(),
        clarification_plan_id=plan_id,
        clarification_plan_payload=plan.model_dump(mode="json"),
        release_binding=binding,
    )


def _question_integrity(service, plan, question):
    definition = next(d for d in plan.cause_definitions if d.cause_id == question.cause_id)
    seeds = [
        dict(value=o.value, source_occurrence_refs=o.source_occurrence_refs)
        for o in question.options
    ]
    identity = dict(
        scope=plan.scope,
        cause_id=definition.cause_id,
        offer_ordinal=question.offer_ordinal,
        offer_trigger=question.offer_trigger,
        trigger_fingerprint=evidence_hash(question.trigger_ref),
        revision_id=UUID(plan.design_revision_id),
        release_pin=definition.release_pin,
        artifact_pins=plan.artifact_pins,
        semantic_question_id=question.semantic_question_id,
        source_occurrence_refs=definition.source_candidate_refs,
        option_seeds=seeds,
    )
    if question.clarification_id != stable_id(
        "clarification_", "jewelai.f04.question/2.0.0", identity
    ):
        raise ValueError("Question identity mismatch")
    entry = service.artifacts.questions.get_question(question.semantic_question_id)
    for option in question.options:
        dictionary = service.artifacts.dictionary[option.value]
        if (
            dictionary.lifecycle != EntryLifecycle.ACTIVE
            or dictionary.category != entry.answer_contract.dictionary_category
            or dictionary.canonical_terms.for_locale(question.locale) != option.label
        ):
            raise ValueError("Question Dictionary option mismatch")
        expected = stable_id(
            "option_",
            "jewelai.f04.option/1.0.0",
            dict(
                question_id=question.clarification_id,
                value=option.value,
                dictionary_category=dictionary.category,
                dictionary_artifact_version=plan.artifact_pins.dictionary_artifact_version,
                dictionary_sha256=plan.artifact_pins.dictionary_sha256,
            ),
        )
        if option.option_id != expected:
            raise ValueError("Option identity mismatch")
    if question.semantic_question_id == "METAL_MATERIAL":
        conflict = next(c for c in plan.conflicts if c.conflict_id == definition.source_conflict_id)
        if tuple(o.value for o in question.options) != conflict.normalized_values:
            raise ValueError("Material choices do not match original explicit sources")
        for option in question.options:
            expected_refs = tuple(
                (o.message_id, o.candidate_id, o.message_content_sha256)
                for o in conflict.occurrences
                if o.normalized_dictionary_id == option.value
            )
            if (
                tuple(
                    (r.message_id, r.candidate_id, r.message_content_sha256)
                    for r in option.source_occurrence_refs
                )
                != expected_refs
            ):
                raise ValueError("Material choice source occurrence mismatch")
        wording = service.artifacts.questions.render(
            "METAL_MATERIAL", plan.role_id, plan.locale.value
        ).wording
        expected = wording.format(
            options=(" или " if plan.locale == "ru" else " or ").join(
                o.label for o in question.options
            )
        )
        if question.text != expected:
            raise ValueError("Material question wording differs from pinned catalog")


def _verify_source_evaluation(
    service, repo, session_id, organization_id, plan, cycle, message, verified, *, correction=None
):
    version = (
        correction.parsed_correction.parse_version
        if correction
        else (cycle.result.parser_evidence_version or "1.2.0")
    )
    with _source_governance(version):
        return _verify_recorded_source_evaluation(
            service,
            repo,
            session_id,
            organization_id,
            plan,
            cycle,
            message,
            verified,
            correction=correction,
        )


def _verify_recorded_source_evaluation(
    service, repo, session_id, organization_id, plan, cycle, message, verified, *, correction=None
):
    """Reverify the one recorded transition; never rebuild canonical state from chat."""
    source_revision = repo.get_revision(
        session_id, cycle.result.context.source_revision_id, organization_id
    )
    current = repo.get_revision(session_id, cycle.specification_revision_id, organization_id)
    _, source = source_message(
        service, session_id, message.message_id, organization_id, repository=repo
    )
    context = input_context(
        plan.scope,
        source_revision,
        cycle.enrichment_cycle_id,
        cycle.cycle_number,
        service.artifacts,
        cycle.release_pin,
    )
    if context != cycle.result.context:
        raise ValueError("Enrichment input context does not match actual source event")
    parsed = _parse_recorded_message(
        message.content,
        parse_version=(
            correction.parsed_correction.parse_version
            if correction
            else cycle.result.parser_evidence_version or "1.2.0"
        ),
        locale=plan.locale.value,
        dictionary=service.artifacts.dictionary,
        knowledge_runtime=verified.compiled_runtime,
    )
    if correction is not None:
        if not same_parse_evidence(correction.parsed_correction, parsed):
            raise ValueError("Correction parse does not match its source Message")
        # Validate the retained evaluation in its original evidence format. Only
        # the current 1.2 interpreter above reads text; no legacy parse is run.
        parsed = correction.parsed_correction
    conflict = product_body_material_conflict(
        parsed,
        message=message,
        context=context,
        dictionary=service.artifacts.dictionary,
        knowledge_runtime=verified.compiled_runtime,
    )
    equivalents = (
        tuple(o.candidate_id for o in conflict.occurrences)
        if conflict and conflict.kind == "equivalent"
        else ()
    )
    kwargs = {"equivalent_candidate_ids": equivalents} if equivalents else {}
    before = service._evaluate(source_revision, parsed, source, **kwargs)
    proposed = proposed_design_for_transition(source_revision, before)
    if current.design != proposed or (current.revision_id == source_revision.revision_id) != (
        proposed == source_revision.design
    ):
        # A rejected canonical transition can be retained only as a rejected result,
        # never as accepted target evidence or causal discharge.
        if (
            correction is None
            or correction.outcome not in {"DEFERRED", "REJECTED"}
            or current != source_revision
        ):
            raise ValueError("Stored revision is not the actual accepted ParserProposal transition")
    if current.revision_id != source_revision.revision_id and (
        current.parent_revision_id != source_revision.revision_id or current.event.source != source
    ):
        raise ValueError("Canonical transition source/ancestry mismatch")
    post = service._evaluate(current, parsed, source, **kwargs)
    expected = f04_evaluation(post, revision=current, context=context)
    if expected.enrichment_result != cycle.result:
        raise ValueError("Stored Matrix result does not match deterministic source evaluation")
    if correction is not None:
        first = f04_evaluation(before, revision=source_revision, context=context)
        if (
            correction.parsed_correction != parsed
            or correction.correction_evaluation != first
            or correction.post_transition_evaluation != expected
        ):
            raise ValueError("Correction source/proposal audit was altered")
        accepted = correction_accepted_targets(
            first,
            source_revision,
            current,
            scope=plan.scope,
            source_message_id=message.message_id,
            outcome=correction.outcome,
        )
        if accepted != correction.accepted_target_evidence:
            raise ValueError("Correction acceptance is not backed by its actual ParserProposal")
    return expected


def _verify_answer_transition(
    service,
    repo,
    session_id,
    organization_id,
    previous,
    plan,
    event,
    message,
    cycle,
    previous_cycle,
):
    before = repo.get_revision(session_id, event.previous_revision_id, organization_id)
    after = repo.get_revision(
        session_id, event.new_revision_id or event.previous_revision_id, organization_id
    )
    _, source = source_message(
        service, session_id, message.message_id, organization_id, repository=repo
    )
    question = next(q for q in previous.questions if q.clarification_id == event.clarification_id)
    if event.decision not in question.allowed_decisions or event.target != question.target:
        raise ValueError("Answer decision/target does not belong to the original offer")
    request = SimpleNamespace(
        decision=event.decision,
        selected_option=event.selected_option.value
        if event.selected_option and event.decision == "SELECT_OPTION"
        else None,
    )
    option = _resolve_decision(question, request)
    if event.selected_option != option or event.selected_option_id != (
        option.option_id if option else None
    ):
        raise ValueError("Answer option does not match the original offered ID/value")
    if event.outcome in {"APPLIED", "NO_CHANGE"}:
        if option is None:
            raise ValueError("Accepted answer has no valid explicit option")
        if event.outcome == "APPLIED":
            proposal = _parser_proposal(
                question,
                option,
                SimpleNamespace(source=source),
                before,
                service.artifacts.dictionary,
                **(
                    {
                        "_target": ParserTarget.METAL_MATERIAL,
                        "_category": DictionaryCategory.METAL_MATERIAL,
                    }
                    if question.semantic_question_id == "METAL_MATERIAL"
                    else {}
                ),
            )
            if (
                proposal is None
                or proposal.issues
                or not proposal.has_changes
                or proposal.proposed_design != after.design
                or protected_target(before, question.target, previous.constraint_evidence)
                or after.event.source != source
            ):
                raise ValueError("Accepted answer is not its authorized canonical ParserProposal")
        elif (
            before != after
            or not isinstance(target_state(before, question.target), KnownValue)
            or target_state(before, question.target).value != option.value
        ):
            raise ValueError("Same-value answer lacks exact current canonical proof")
        expected = (
            accepted_target(
                before,
                after,
                question.target.concrete_target,
                scope=previous.scope,
                source_message_id=message.message_id,
                candidate_ids=question.source_candidate_ids,
                normalization_refs=(option.option_id, option.value),
            ),
        )
        if expected != event.accepted_target_evidence:
            raise ValueError("Answer accepted-target evidence is incomplete or fabricated")
    elif event.accepted_target_evidence or before != after or event.new_revision_id is not None:
        raise ValueError("Unaccepted answer cannot mutate canonical state")
    if event.new_revision_id is None:
        if cycle.result != previous_cycle.result:
            raise ValueError("Nonmutating answer changed immutable enrichment evidence")
    else:
        base = enrich_prompt_with_active_release(
            after,
            service.artifacts.prompts,
            service.artifact_store,
            knowledge_package_id=cycle.release_pin.package_id,
            knowledge_artifact_version=cycle.release_pin.artifact_version,
            active_release=service.active_release,
            validation_report=service.validation_report,
            proposals=tuple(d.proposal for d in previous_cycle.result.decisions),
            **service._parametric_kwargs(after),
        )
        context = input_context(
            previous.scope,
            before,
            cycle.enrichment_cycle_id,
            cycle.cycle_number,
            service.artifacts,
            cycle.release_pin,
        )
        with _source_governance(cycle.result.parser_evidence_version or "1.2.0"):
            if f04_enrichment(base, revision=after, context=context) != cycle.result:
                raise ValueError("Answer enrichment does not match the exact accepted transition")


def _verify_source_plan(
    service,
    repo,
    plan,
    revision,
    evaluation,
    source,
    *,
    previous=None,
    states=None,
    reoffers=None,
    offers=(),
):
    """Validate source-to-plan evidence, not just a self-consistent stored hash."""
    constraints = merge_constraint_evidence(
        evaluation,
        session_id=plan.scope.session_id,
        organization_id=plan.scope.organization_id,
        source=source,
        authoritative_revision=revision,
        enrichment_cycle_id=plan.enrichment_cycle_id,
        previous=previous.constraint_evidence if previous else (),
        _handled_candidate_ids=tuple(
            o.candidate_id
            for c in plan.conflicts
            if c.context.source_enrichment_cycle_id == plan.enrichment_cycle_id
            and c.kind != "equivalent"
            for o in c.occurrences
        ),
        load_source_revision=lambda rid: repo.get_revision(
            plan.scope.session_id, rid, plan.scope.organization_id
        ),
    )
    if constraints != plan.constraint_evidence:
        raise ValueError("Constraint lineage differs from actual source evaluation")
    expected = plan_f04(
        revision,
        evaluation,
        artifacts=service.artifacts,
        role_id=plan.role_id,
        plan_id=plan.plan_id,
        cycle_id=plan.enrichment_cycle_id,
        cycle_number=plan.enrichment_cycle_number,
        trigger=plan.trigger,
        conflicts=tuple(
            c
            for c in plan.conflicts
            if c.context.source_enrichment_cycle_id == plan.enrichment_cycle_id
        ),
        previous_plan=previous,
        current_states=states,
        constraint_evidence=constraints,
        relevant_changes=reoffers,
        offer_history=offers,
    )
    if expected != plan:
        raise ValueError("F plan is not the pinned deterministic source/frontier projection")


def _verify_new_causes(service, plan, revision, previous=None):
    from jewelai_domain.rules import analyze_gaps

    from .f04_planning import canonical_target, open_cause_state

    old = {c.cause_id: c for c in previous.cause_definitions} if previous else {}
    states = {s.cause_id: s for s in plan.frontier_core.cause_states}
    gaps = {
        g.concrete_target: g
        for g in analyze_gaps(
            revision,
            questions=service.artifacts.questions,
            required_targets=service.artifacts.rules.required_targets,
        )
    }
    if not set(old).issubset({d.cause_id for d in plan.cause_definitions}):
        raise ValueError("Cause history was deleted")
    for cause in plan.cause_definitions:
        if cause.cause_id in old:
            if cause != old[cause.cause_id]:
                raise ValueError("Immutable cause definition was rewritten")
            continue
        if (
            cause.origin_plan_id != plan.plan_id
            or cause.origin_cycle_id != plan.enrichment_cycle_id
            or cause.origin_revision_id != revision.revision_id
            or cause.scope != plan.scope
            or cause.artifact_pins != plan.artifact_pins
            or cause.target
            != canonical_target(revision, cause.target.concrete_target, scope=plan.scope)
            or (
                cause.release_pin.package_id,
                cause.release_pin.artifact_version,
                cause.release_pin.runtime_sha256,
                cause.release_pin.validation_report_sha256,
            )
            != (
                plan.knowledge_package_id,
                plan.knowledge_artifact_version,
                plan.knowledge_runtime_sha256,
                plan.knowledge_validation_report_sha256,
            )
        ):
            raise ValueError("New cause origin/owner/release does not match its actual plan")
        if cause.kind.startswith("material_"):
            conflict = next(c for c in plan.conflicts if c.conflict_id == cause.source_conflict_id)
            if (
                cause.kind != "material_" + conflict.kind
                or cause.target != conflict.target
                or cause.resolution_predicate.kind != "material_choice"
                or cause.resolution_predicate.offered_values != conflict.normalized_values
                or cause.rule_ref.rule_id != "ask_unresolved_product_body_material"
            ):
                raise ValueError("Material cause does not match its explicit source conflict")
        elif cause.kind == "information_gap":
            gap = gaps.get(cause.target.concrete_target)
            rule = service.artifacts.rules[cause.rule_ref.rule_id]
            if (
                gap is None
                or not gap.required
                or gap.state == "satisfied"
                or rule.target != gap.target
                or rule.action.kind != "ask"
                or cause.resolution_predicate.kind != "gap_satisfied"
                or cause.resolution_predicate.original_gap_state != gap.state
            ):
                raise ValueError("Information cause is not an actual pinned Rules gap")
        if cause.rule_ref is not None:
            rule = service.artifacts.rules[cause.rule_ref.rule_id]
            if (
                cause.rule_ref.artifact_sha256 != plan.artifact_pins.rules_sha256
                or cause.rule_ref.rule_version != rule.rule_version
            ):
                raise ValueError("Cause Rules provenance mismatch")
        expected = open_cause_state(
            cause,
            criticality="BLOCKING"
            if cause.kind == "information_gap"
            or (
                cause.kind.startswith("material_")
                and not protected_target(revision, cause.target, plan.constraint_evidence)
            )
            else "NONBLOCKING",
            offer_state="PROTECTED"
            if protected_target(revision, cause.target, plan.constraint_evidence)
            else "AVAILABLE",
        )
        if states[cause.cause_id] != expected:
            raise ValueError("New cause cannot claim fabricated acceptance or dormancy")


def _history(service, repo, session_id, organization_id):
    with repo.read_enrichment_history(session_id, organization_id) as reader:
        return _history_frame(service, reader, session_id, organization_id)


def _history_frame(service, repo, session_id, organization_id):
    session = repo.get_design_session(session_id, organization_id)
    cycles = repo.list_enrichment_cycles(session_id, organization_id)
    if not cycles:
        fail(Error.ENRICHMENT_CYCLE_MISMATCH, "Session has no durable enrichment cycle")
    verified = repo.restore_pinned_knowledge_runtime(
        session_id,
        organization_id,
        service.artifact_store,
        active_release=service.active_release,
        validation_report=service.validation_report,
    )
    records = repo.list_clarification_plans(session_id, organization_id)
    by_cycle = {r.enrichment_cycle_id: r for r in records}
    answer_records = repo.list_clarification_answers(session_id, organization_id)
    correction_records = repo.list_user_corrections(session_id, organization_id)
    answers = {
        r.answer_record_id: (r, decode_answer_result(r.result_payload)) for r in answer_records
    }
    corrections = {
        r.correction_record_id: (r, decode_correction_result(r.result_payload))
        for r in correction_records
    }
    plans = []
    for index, cycle in enumerate(cycles, 1):
        if cycle.cycle_number != index or cycle.enrichment_cycle_id not in by_cycle:
            raise ValueError("F cycles/plans are not complete and append-only")
        record = by_cycle[cycle.enrichment_cycle_id]
        plan = ClarificationPlanV2.model_validate(record.plan_payload)
        revision = repo.get_revision(session_id, cycle.specification_revision_id, organization_id)
        pins = artifact_pins(service.artifacts, revision)
        scope = EvidenceScope(
            organization_id=organization_id, session_id=session_id, design_id=revision.design_id
        )
        if (
            plan.scope != scope
            or plan.plan_id != record.clarification_plan_id
            or plan.enrichment_cycle_id != cycle.enrichment_cycle_id
            or plan.enrichment_cycle_number != cycle.cycle_number
            or plan.enrichment_result_hash != cycle.result.content_hash
            or plan.revision_sha256 != evidence_hash(revision)
            or plan.artifact_pins != pins
            or cycle.result.context.artifact_pins != pins
        ):
            raise ValueError("Plan/cycle/canonical/artifact binding mismatch")
        service._validate_parametric_lineage(cycle.result)
        _verify_new_causes(service, plan, revision, plans[-1] if plans else None)
        for conflict in plan.conflicts:
            source_revision = repo.get_revision(
                session_id, conflict.context.source_revision_id, organization_id
            )
            if (
                conflict.context.source_revision_sha256 != evidence_hash(source_revision)
                or conflict.context.scope != scope
            ):
                raise ValueError("Conflict origin revision/scope mismatch")
            message, _ = source_message(
                service,
                session_id,
                conflict.occurrences[0].message_id,
                organization_id,
                repository=repo,
            )
            parsed = _parse_recorded_message(
                message.content,
                parse_version=(
                    repo.get_enrichment_cycle(
                        session_id, conflict.context.source_enrichment_cycle_id, organization_id
                    ).result.parser_evidence_version
                    or "1.2.0"
                ),
                locale=plan.locale.value,
                dictionary=service.artifacts.dictionary,
                knowledge_runtime=verified.compiled_runtime,
            )
            actual = product_body_material_conflict(
                parsed,
                message=message,
                context=conflict.context,
                dictionary=service.artifacts.dictionary,
                knowledge_runtime=verified.compiled_runtime,
            )
            if actual != conflict:
                raise ValueError("Conflict does not match retained source evidence")
        if plans:
            previous = plans[-1]
            trigger = plan.trigger
            if (
                trigger.kind == "initial"
                or trigger.previous_plan_id != previous.plan_id
                or trigger.previous_plan_hash != previous.content_hash
            ):
                raise ValueError("Current event does not bind exact previous plan/cycle")
            previous_defs = {d.cause_id: d for d in previous.cause_definitions}
            if any(
                d != previous_defs[d.cause_id]
                for d in plan.cause_definitions
                if d.cause_id in previous_defs
            ):
                raise ValueError("Immutable cause definition was rewritten")
            if trigger.kind in {"answer", "correction"}:
                collection = answers if trigger.kind == "answer" else corrections
                pair = collection.get(trigger.record_id)
                if pair is None or pair[1].content_hash != trigger.content_hash:
                    raise ValueError("Plan references a missing accepted event")
                event_record, event = pair
                message, _ = source_message(
                    service, session_id, trigger.message_id, organization_id, repository=repo
                )
                if (
                    hashlib.sha256(message.content.encode("utf-8")).hexdigest()
                    != trigger.message_content_sha256
                ):
                    raise ValueError("Event source hash mismatch")
                validate_accepted_evidence(repo, session_id, organization_id, event)
                if (
                    event.previous_revision_id != UUID(previous.design_revision_id)
                    or (event.new_revision_id or event.previous_revision_id) != revision.revision_id
                ):
                    raise ValueError("Event is not the actual current canonical transition")
                if trigger.kind == "answer":
                    _verify_answer_transition(
                        service,
                        repo,
                        session_id,
                        organization_id,
                        previous,
                        plan,
                        event,
                        message,
                        cycle,
                        cycles[index - 2],
                    )
                    question = next(
                        q
                        for q in previous.questions
                        if q.clarification_id == event.clarification_id
                    )
                    request = SimpleNamespace(
                        expected_revision_id=event.previous_revision_id,
                        decision=event.decision,
                        selected_option=event.selected_option.value
                        if event.decision == "SELECT_OPTION"
                        else None,
                        selected_option_id=event.selected_option_id
                        if event.decision == "SELECT_OPTION"
                        else None,
                    )
                    if (
                        event.source_plan_id != previous.plan_id
                        or event.plan_content_hash != previous.content_hash
                        or event.answer_hash
                        != answer_intent_hash(previous, question, request, message)
                    ):
                        raise ValueError("Answer source/intent/plan mismatch")
                    expected_assertions = resolving_assertions(
                        previous,
                        event.accepted_target_evidence,
                        revision,
                        method="selected_offered_value",
                        question_id=question.clarification_id,
                        rejected=event.decision == "REJECT",
                        source_message_id=message.message_id,
                    )
                else:
                    source_evaluation = _verify_source_evaluation(
                        service,
                        repo,
                        session_id,
                        organization_id,
                        plan,
                        cycle,
                        message,
                        verified,
                        correction=event,
                    )
                    if (
                        event.previous_enrichment_cycle_id != previous.enrichment_cycle_id
                        or event.previous_enrichment_content_hash != previous.enrichment_result_hash
                        or event.previous_enrichment_cycle_number
                        != previous.enrichment_cycle_number
                    ):
                        raise ValueError("Correction previous-cycle evidence mismatch")
                    expected_assertions = resolving_assertions(
                        previous,
                        event.accepted_target_evidence,
                        revision,
                        method="accepted_correction",
                    )
                if event.resolution_assertions != expected_assertions:
                    raise ValueError("Causal assertions do not satisfy exact predicates")
                expected_states = {
                    s.cause_id: s
                    for s in advance_frontier(
                        previous,
                        event,
                        record_id=trigger.record_id,
                        result_kind="clarification" if trigger.kind == "answer" else "correction",
                    )
                }
                current_states = {s.cause_id: s for s in plan.frontier_core.cause_states}
                before = repo.get_revision(session_id, event.previous_revision_id, organization_id)
                reoffers = relevant_reoffers(
                    previous,
                    event,
                    before,
                    revision,
                    record_id=trigger.record_id,
                    projected_states=tuple(expected_states.values()),
                    offer_history=tuple(q for p in plans for q in p.questions),
                )
                for cid, state in expected_states.items():
                    actual = current_states.get(cid)
                    if actual is None or actual.model_dump(
                        exclude={"offer_state"}
                    ) != state.model_dump(exclude={"offer_state"}):
                        raise ValueError("Current frontier is not the causal event projection")
                    if state.offer_state == "DORMANT" and actual.offer_state == "AVAILABLE":
                        # Relevant-change fingerprints are verified below before reuse.
                        offered = next((q for q in plan.questions if q.cause_id == cid), None)
                        if offered is None or offered.offer_trigger != "relevant_change":
                            raise ValueError("Unapproved automatic re-offer")
                        if cid not in reoffers or offered.trigger_ref != reoffers[cid]:
                            raise ValueError(
                                "Re-offer is not a matching accepted dependency change"
                            )
                    elif actual.offer_state != state.offer_state and not (
                        actual.offer_state == "PROTECTED"
                        and protected_target(
                            revision, actual.availability_target_ref, plan.constraint_evidence
                        )
                    ):
                        raise ValueError("Unproven offer-state change")
                if trigger.kind == "correction":
                    _, actual_source = source_message(
                        service, session_id, message.message_id, organization_id, repository=repo
                    )
                    _verify_source_plan(
                        service,
                        repo,
                        plan,
                        revision,
                        source_evaluation,
                        actual_source,
                        previous=previous,
                        states=tuple(expected_states.values()),
                        reoffers=reoffers,
                        offers=tuple(q for p in plans for q in p.questions),
                    )
            elif trigger.kind == "explicit_resume":
                _validate_resume_history(
                    service, repo, session_id, organization_id, previous, plan, plans
                )
        else:
            if plan.trigger.kind != "initial":
                raise ValueError("First F plan lacks an original input event")
            message, _ = source_message(
                service, session_id, plan.trigger.message_id, organization_id, repository=repo
            )
            source_evaluation = _verify_source_evaluation(
                service, repo, session_id, organization_id, plan, cycle, message, verified
            )
            _, actual_source = source_message(
                service, session_id, message.message_id, organization_id, repository=repo
            )
            _verify_source_plan(service, repo, plan, revision, source_evaluation, actual_source)
        for question in plan.questions:
            _question_integrity(service, plan, question)
        from jewelai_domain.rules_v2 import RuleContextV2

        actual_rule = service.artifacts.rules.evaluate(
            revision,
            session.role_id,
            unresolved_context=RuleContextV2(
                frontier_core=plan.frontier_core, cause_definitions=plan.cause_definitions
            ),
        )
        if actual_rule != plan.rule_decision:
            raise ValueError("Stored Rules2/current frontier decision mismatch")
        plans.append(plan)
    current = repo.get_current_revision(session_id, organization_id)
    if current.revision_id != cycles[-1].specification_revision_id:
        fail(Error.ENRICHMENT_CYCLE_MISMATCH, "Current revision has no matching enrichment cycle")
    referenced_answers = {p.trigger.record_id for p in plans if p.trigger.kind == "answer"}
    referenced_corrections = {p.trigger.record_id for p in plans if p.trigger.kind == "correction"}
    if referenced_answers != set(answers) or referenced_corrections != set(corrections):
        raise ValueError("F decision history has an unbound or missing atomic cycle")
    return session, current, cycles, tuple(plans), answers, corrections


@boundary
def restore_clarification_plan(service, session_id, organization_id, plan_id, *, require_current):
    _, _, _, plans, _, _ = _history(service, service.repository, session_id, organization_id)
    plan = next((p for p in plans if p.plan_id == plan_id), None)
    if plan is None:
        fail(Error.SESSION_NOT_FOUND, "Plan was not found in session scope")
    if require_current and plan.plan_id != plans[-1].plan_id:
        fail(Error.STALE_CLARIFICATION_PLAN, "Clarification plan is no longer current")
    return plan


def _snapshot(service, repo, session_id, organization_id):
    session, revision, cycles, plans, answers, corrections = _history(
        service, repo, session_id, organization_id
    )
    latest, plan = cycles[-1], plans[-1]
    answer_values = tuple(v for _, v in answers.values())
    correction_values = tuple(v for _, v in corrections.values())
    # Existing normalized audit lineage keeps historical flags/content hashes exactly.
    # Only the target adapter changes its representation for the new TargetRef shape.
    lineage = []
    from jewelai_prompts import FinalPromptDecisionLineage

    for answer in answer_values:
        lineage.append(
            FinalPromptDecisionLineage(
                kind="clarification",
                session_id=session_id,
                decision_id=answer.clarification_id,
                decision=answer.decision.value,
                outcome=answer.outcome.value,
                target=answer.target.concrete_target,
                selected_value=answer.selected_option.value if answer.selected_option else None,
                source_revision_id=answer.previous_revision_id,
                resulting_revision_id=answer.new_revision_id,
                applies_to_revision_id=revision.revision_id,
                knowledge_package_id=answer.knowledge_package_id,
                knowledge_artifact_version=answer.knowledge_artifact_version,
                knowledge_runtime_sha256=answer.knowledge_runtime_sha256,
                knowledge_validation_report_sha256=answer.knowledge_validation_report_sha256,
                question_artifact_version=answer.question_artifact_version,
                rules_artifact_version=answer.rules_artifact_version,
                blocks_progression=answer.blocks_progression,
                content_hash=answer.content_hash,
            )
        )
    if correction_values:
        lineage.extend(
            _decision_lineage(
                session_id,
                revision.revision_id,
                (),
                correction_values,
                {c.content_hash: c.outcome == "DEFERRED" for c in correction_values},
            )
        )
    pin = latest.release_pin
    snapshot = FinalPromptSnapshotV2(
        schema_version="2.0.0",
        contract_profile=F04_PROFILE,
        session_id=session_id,
        organization_id=organization_id,
        locale=session.locale,
        revision=revision,
        enrichment_cycle_id=latest.enrichment_cycle_id,
        latest_enrichment_cycle_id=latest.enrichment_cycle_id,
        enrichment_cycle_number=latest.cycle_number,
        enrichment_result=latest.result,
        knowledge_release=KnowledgeReleaseReference(
            package_id=pin.package_id,
            artifact_version=pin.artifact_version,
            runtime_sha256=pin.runtime_sha256,
            validation_report_sha256=pin.validation_report_sha256,
        ),
        artifact_versions=FinalPromptArtifactVersions(
            design_schema_version=revision.schema_version,
            dictionary_artifact_version=service.artifacts.versions.dictionary,
            question_artifact_version="2.0.0",
            rules_artifact_version="2.0.0",
            prompt_template_artifact_version=service.artifacts.versions.prompts,
            enrichment_version="2.0.0",
        ),
        rule_decision=plan.rule_decision,
        decision_lineage=tuple(
            sorted(lineage, key=lambda d: (d.kind, d.decision_id, d.content_hash))
        ),
        constraint_evidence=plan.constraint_evidence,
        effective_unresolved_frontier=seal_frontier(plan, plans),
        cause_definitions=plan.cause_definitions,
    )
    return snapshot, plan, answers, corrections


@boundary
def build_preparation_source(service, repo, session_id, organization_id):
    snapshot, plan, answers, corrections = _snapshot(service, repo, session_id, organization_id)
    return _preparation_context(service, snapshot, plan, answers, corrections)


def _preparation_context(service, snapshot, plan, answers, corrections):
    session_id, organization_id = snapshot.session_id, snapshot.organization_id
    assembly = assemble_internal_final_prompt_v3(
        snapshot, dictionary=service.artifacts.dictionary, templates=service.artifacts.prompts
    )
    handoff = build_internal_final_prompt_handoff(assembly)
    audit = DecisionFrontier(
        answers=tuple(
            DecisionReference(record_id=i, content_hash=r.content_hash)
            for i, (r, _) in sorted(answers.items(), key=lambda p: str(p[0]))
        ),
        corrections=tuple(
            DecisionReference(record_id=i, content_hash=r.content_hash)
            for i, (r, _) in sorted(corrections.items(), key=lambda p: str(p[0]))
        ),
    )
    gate = PreparationGateEvidenceV2(
        schema_version="2.0.0",
        contract_profile=F04_PROFILE,
        organization_id=organization_id,
        session_id=session_id,
        revision=snapshot.revision,
        enrichment_cycle_id=snapshot.enrichment_cycle_id,
        enrichment_cycle_number=snapshot.enrichment_cycle_number,
        enrichment_result_hash=snapshot.enrichment_result.content_hash,
        source_handoff_hash=handoff.content_hash,
        knowledge_release=snapshot.knowledge_release,
        rule_decision=snapshot.rule_decision,
        workflow_status=_workflow_status(assembly, plan).value,
        clarification_plan_id=plan.plan_id,
        clarification_plan_hash=plan.content_hash,
        blocking_clarification_ids=tuple(
            sorted(
                ref.question_id
                for ref in snapshot.effective_unresolved_frontier.origin_question_refs
                if any(
                    s.cause_id == ref.cause_id and s.blocks_current
                    for s in plan.frontier_core.cause_states
                )
            )
        ),
        decision_frontier=audit,
        decision_frontier_hash=preparation_hash("jewelai.preparation.frontier/1.0.0", audit),
        release_verified=True,
        availability_overlay_hash=snapshot.enrichment_result.availability_overlay.content_hash,
        effective_unresolved_frontier_hash=snapshot.effective_unresolved_frontier.content_hash,
    )
    return handoff, gate


@boundary
def get_current_state(service, session_id, organization_id):
    snapshot, plan, answers, corrections = _snapshot(
        service, service.repository, session_id, organization_id
    )
    assembly = assemble_internal_final_prompt_v3(
        snapshot, dictionary=service.artifacts.dictionary, templates=service.artifacts.prompts
    )
    handoff, gate = _preparation_context(service, snapshot, plan, answers, corrections)
    from jewelai_prompts import GenerationPreparationError
    from jewelai_prompts.downstream_preparation_v2 import render_semantic_source_v2

    from .generation_preparations import preparation_expectations

    try:
        render_semantic_source_v2(handoff, gate)
        can_prepare = True
    except GenerationPreparationError:
        can_prepare = False
    return PromptEnrichmentWorkflowStateV2(
        schema_version="2.0.0",
        contract_profile=F04_PROFILE,
        current_plan_version="2.0.0",
        session_id=session_id,
        organization_id=organization_id,
        authoritative_revision_id=snapshot.revision.revision_id,
        enrichment_cycle_id=snapshot.enrichment_cycle_id,
        enrichment_cycle_number=snapshot.enrichment_cycle_number,
        knowledge_release=snapshot.knowledge_release,
        status=_workflow_status(assembly, plan),
        clarification_plan_id=plan.plan_id,
        clarification_plan=plan,
        final_output=assembly,
        preparation_expectations=preparation_expectations(handoff, gate),
        can_prepare=can_prepare,
        availability_overlay_hash=snapshot.enrichment_result.availability_overlay.content_hash,
        effective_unresolved_frontier_hash=snapshot.effective_unresolved_frontier.content_hash,
        current_unresolved_causal_summaries=tuple(
            s for s in plan.frontier_core.cause_states if s.status == "OPEN"
        ),
    )


@boundary
def record_persisted_clarification_answer(service, organization_id, request):
    request = PersistedClarificationAnswerRequestV2.model_validate(request)
    repo = service.repository
    session, current, cycles, plans, answers, _ = _history(
        service, repo, request.session_id, organization_id
    )
    plan = next((p for p in plans if p.plan_id == request.clarification_plan_id), None)
    if plan is None:
        fail(Error.SESSION_NOT_FOUND, "Plan was not found in session scope")
    if plan.content_hash != request.plan_content_hash:
        fail(Error.INVALID_CLARIFICATION_PLAN, "Plan content hash mismatch")
    question = next(
        (q for q in plan.questions if q.clarification_id == request.clarification_id), None
    )
    if question is None:
        fail(Error.INVALID_CLARIFICATION_ANSWER, "Question does not belong to the plan")
    message, source = source_message(
        service, request.session_id, request.message_id, organization_id
    )
    intent_hash = answer_intent_hash(plan, question, request, message)
    for record, answer in answers.values():
        if (answer.plan_content_hash, answer.clarification_id) == (
            plan.content_hash,
            question.clarification_id,
        ) or record.answer_record_id == request.answer_id:
            if answer.answer_hash != intent_hash:
                fail(
                    Error.CLARIFICATION_CONFLICT, "Answer identity already has a different decision"
                )
            return answer, get_current_state(service, request.session_id, organization_id)
    if plan.plan_id != plans[-1].plan_id:
        fail(Error.STALE_CLARIFICATION_PLAN, "Clarification plan is no longer current")
    if current.revision_id != request.expected_revision_id or plan.design_revision_id != str(
        current.revision_id
    ):
        fail(Error.STALE_REVISION, "Product State revision changed before the answer")
    if request.decision not in question.allowed_decisions:
        fail(Error.INVALID_CLARIFICATION_DECISION, "Decision is not allowed for this question")
    option = _resolve_decision(question, request)
    if request.decision == "SELECT_OPTION" and option.option_id != request.selected_option_id:
        fail(Error.INVALID_CLARIFICATION_OPTION, "Selected option ID and value do not match")
    authoritative = current
    accepted = ()
    assertions = ()
    question_resolved = False
    if request.decision in {"SKIP", "UNKNOWN", "REJECT"}:
        outcome, reason = {
            "SKIP": ("SKIPPED", "user_skipped"),
            "UNKNOWN": ("UNKNOWN", "user_does_not_know"),
            "REJECT": ("REJECTED", "user_rejected_offer"),
        }[request.decision.value]
        question_resolved = request.decision == "REJECT"
        assertions = resolving_assertions(
            plan,
            (),
            current,
            method="selected_offered_value",
            question_id=question.clarification_id,
            rejected=question_resolved,
            source_message_id=message.message_id,
        )
    else:
        state = target_state(current, question.target)
        if isinstance(state, KnownValue) and state.value == option.value:
            outcome, reason = "NO_CHANGE", "value_already_current"
            question_resolved = True
        elif protected_target(current, question.target, plan.constraint_evidence):
            outcome, reason = "DEFERRED", "target_protected"
        else:
            answer = SimpleNamespace(source=source)
            proposal = _parser_proposal(
                question,
                option,
                answer,
                current,
                service.artifacts.dictionary,
                **(
                    {
                        "_target": ParserTarget.METAL_MATERIAL,
                        "_category": DictionaryCategory.METAL_MATERIAL,
                    }
                    if question.semantic_question_id == "METAL_MATERIAL"
                    else {}
                ),
            )
            if proposal is None or proposal.issues or not proposal.has_changes:
                outcome, reason = "DEFERRED", "parser_rejected"
            else:
                try:
                    authoritative = revise_design(
                        current,
                        proposal.proposed_design,
                        expected_revision_id=current.revision_id,
                        source=source,
                        reason="Applied an explicitly authorized F04 clarification choice",
                        created_at=service._clock(),
                    )
                    outcome, reason = "APPLIED", "user_selected_offered_option"
                    question_resolved = True
                except RevisionConflict:
                    outcome, reason = "DEFERRED", "parser_rejected"
        if question_resolved:
            accepted = (
                accepted_target(
                    current,
                    authoritative,
                    question.target.concrete_target,
                    scope=plan.scope,
                    source_message_id=message.message_id,
                    candidate_ids=question.source_candidate_ids,
                    normalization_refs=(option.option_id, option.value),
                ),
            )
            assertions = resolving_assertions(
                plan,
                accepted,
                authoritative,
                method="selected_offered_value",
                question_id=question.clarification_id,
            )
    payload = dict(
        answer_version="2.0.0",
        contract_profile=F04_PROFILE,
        scope=plan.scope,
        source_plan_id=plan.plan_id,
        session_id=request.session_id,
        plan_content_hash=plan.content_hash,
        clarification_id=question.clarification_id,
        semantic_question_id=question.semantic_question_id,
        decision=request.decision,
        selected_option=option,
        selected_option_id=option.option_id if option else None,
        source_candidate_ids=question.source_candidate_ids,
        source_proposal_ids=question.source_proposal_ids,
        evidence=question.evidence,
        target=question.target,
        subject=question.subject,
        previous_revision_id=current.revision_id,
        new_revision_id=authoritative.revision_id if authoritative != current else None,
        resulting_revision=authoritative if authoritative != current else None,
        knowledge_package_id=plan.knowledge_package_id,
        knowledge_artifact_version=plan.knowledge_artifact_version,
        knowledge_runtime_sha256=plan.knowledge_runtime_sha256,
        knowledge_validation_report_sha256=plan.knowledge_validation_report_sha256,
        question_artifact_version="2.0.0",
        rules_artifact_version="2.0.0",
        outcome=outcome,
        reason=reason,
        question_resolved=question_resolved,
        blocks_progression=any(
            s.cause_id == question.cause_id and s.blocks_current
            for s in plan.frontier_core.cause_states
        )
        and not question_resolved,
        answer_hash=intent_hash,
        accepted_target_evidence=accepted,
        resolution_assertions=assertions,
    )
    result = ClarificationAnswerResultV2(**payload, content_hash=evidence_hash(payload))
    next_cycle, next_plan_id = service._uuid(), service._uuid()
    latest = cycles[-1]
    if authoritative != current:
        base = enrich_prompt_with_active_release(
            authoritative,
            service.artifacts.prompts,
            service.artifact_store,
            knowledge_package_id=latest.release_pin.package_id,
            knowledge_artifact_version=latest.release_pin.artifact_version,
            active_release=service.active_release,
            validation_report=service.validation_report,
            proposals=tuple(d.proposal for d in latest.result.decisions),
            **service._parametric_kwargs(authoritative),
        )
        context = input_context(
            plan.scope,
            current,
            next_cycle,
            latest.cycle_number + 1,
            service.artifacts,
            latest.release_pin,
        )
        enriched = f04_enrichment(base, revision=authoritative, context=context)
    else:
        enriched = latest.result
    trigger = AcceptedResultTrigger(
        kind="answer",
        record_id=request.answer_id,
        content_hash=result.content_hash,
        previous_plan_id=plan.plan_id,
        previous_plan_hash=plan.content_hash,
        message_id=message.message_id,
        message_content_sha256=hashlib.sha256(message.content.encode("utf-8")).hexdigest(),
    )
    states = advance_frontier(
        plan, result, record_id=request.answer_id, result_kind="clarification"
    )
    offers = tuple(q for p in plans for q in p.questions)
    relevant = relevant_reoffers(
        plan,
        result,
        current,
        authoritative,
        record_id=request.answer_id,
        projected_states=states,
        offer_history=offers,
    )
    next_plan = plan_f04(
        authoritative,
        enriched,
        artifacts=service.artifacts,
        role_id=session.role_id,
        plan_id=next_plan_id,
        cycle_id=next_cycle,
        cycle_number=latest.cycle_number + 1,
        trigger=trigger,
        previous_plan=plan,
        current_states=states,
        constraint_evidence=plan.constraint_evidence,
        answered_ids=tuple(a.clarification_id for _, a in answers.values())
        + (result.clarification_id,),
        offer_history=offers,
        relevant_changes=relevant,
    )
    committed = repo.commit_clarification_answer(
        answer_record_id=request.answer_id,
        clarification_plan_id=plan.plan_id,
        session_id=request.session_id,
        organization_id=organization_id,
        expected_revision_id=current.revision_id,
        result_payload=result.model_dump(mode="json"),
        created_at=service._clock(),
        next_enrichment_cycle_id=next_cycle,
        next_enrichment_result=enriched,
        next_clarification_plan_id=next_plan_id,
        next_clarification_plan_payload=next_plan.model_dump(mode="json"),
    )
    return decode_answer_result(committed.result_payload), get_current_state(
        service, request.session_id, organization_id
    )


@boundary
def apply_persisted_user_correction(service, organization_id, request):
    request = PersistedUserCorrectionRequestV2.model_validate(request)
    repo = service.repository
    session, current, cycles, plans, answers, corrections = _history(
        service, repo, request.session_id, organization_id
    )
    latest, plan = cycles[-1], plans[-1]
    message, source = source_message(
        service, request.session_id, request.message_id, organization_id
    )
    if any(c.source.message_id == str(message.message_id) for _, c in corrections.values()):
        fail(Error.CORRECTION_CONFLICT, "Correction source already has a durable result")
    if request.expected_revision_id != current.revision_id:
        fail(Error.STALE_REVISION, "Product State revision changed before correction")
    if (
        request.expected_enrichment_cycle_id != latest.enrichment_cycle_id
        or request.expected_enrichment_result_hash != latest.result.content_hash
    ):
        fail(Error.ENRICHMENT_CYCLE_MISMATCH, "Correction enrichment frame changed")
    if request.expected_clarification_plan_hash != plan.content_hash:
        fail(Error.STALE_CLARIFICATION_PLAN, "Correction clarification frame changed")
    cycle_id, plan_id, record_id = service._uuid(), service._uuid(), service._uuid()
    context = input_context(
        plan.scope,
        current,
        cycle_id,
        latest.cycle_number + 1,
        service.artifacts,
        latest.release_pin,
    )
    verified = repo.restore_pinned_knowledge_runtime(
        request.session_id,
        organization_id,
        service.artifact_store,
        active_release=service.active_release,
        validation_report=service.validation_report,
    )
    parsed = parse_full_message(
        message.content,
        locale=session.locale,
        dictionary=service.artifacts.dictionary,
        knowledge_runtime=verified.compiled_runtime,
    )
    conflict = product_body_material_conflict(
        parsed,
        message=message,
        context=context,
        dictionary=service.artifacts.dictionary,
        knowledge_runtime=verified.compiled_runtime,
    )
    equivalent = (
        tuple(o.candidate_id for o in conflict.occurrences)
        if conflict and conflict.kind == "equivalent"
        else ()
    )
    correction = UserCorrection(
        session_id=request.session_id,
        expected_revision_id=current.revision_id,
        correction_text=message.content,
        locale=session.locale,
        source=source,
        previous_enrichment_cycle_id=latest.enrichment_cycle_id,
        previous_enrichment_cycle_number=latest.cycle_number,
        previous_enrichment_content_hash=latest.result.content_hash,
        knowledge_package_id=latest.release_pin.package_id,
        knowledge_artifact_version=latest.release_pin.artifact_version,
        knowledge_runtime_sha256=latest.release_pin.runtime_sha256,
        knowledge_validation_report_sha256=latest.release_pin.validation_report_sha256,
        dictionary_artifact_version=service.artifacts.versions.dictionary,
        prompt_template_artifact_version=service.artifacts.versions.prompts,
    )

    def evaluate(revision, parsed_correction, internal_request, **kwargs):
        if parsed_correction != parsed:
            raise ValueError("Correction source parse mismatch")
        base = service._evaluate(
            revision,
            parsed_correction,
            source,
            **({"equivalent_candidate_ids": equivalent} if equivalent else {}),
        )
        return f04_evaluation(base, revision=revision, context=context)

    def finalize(payload):
        accepted = correction_accepted_targets(
            payload["correction_evaluation"],
            current,
            payload["authoritative_revision"],
            scope=plan.scope,
            source_message_id=message.message_id,
            outcome=payload["outcome"],
        )
        payload.update(
            correction_version="2.0.0",
            contract_profile=F04_PROFILE,
            scope=plan.scope,
            accepted_target_evidence=accepted,
            resolution_assertions=resolving_assertions(
                plan, accepted, payload["authoritative_revision"], method="accepted_correction"
            ),
        )
        return payload

    result = process_user_correction(
        correction,
        authoritative_session_id=request.session_id,
        current_revision=current,
        previous_cycle=latest,
        prior_answer_results=(),
        dictionary=service.artifacts.dictionary,
        templates=service.artifacts.prompts,
        artifact_store=service.artifact_store,
        active_release=verified,
        validation_report=service.validation_report,
        parametric_knowledge=service.artifacts.parametric_knowledge,
        created_at=service._clock(),
        _evaluation_builder=evaluate,
        _result_type=CorrectionReenrichmentResultV2,
        _answer_reader=ClarificationAnswerResultV2,
        _finalize_payload=finalize,
    )
    constraints = merge_constraint_evidence(
        result.post_transition_evaluation,
        session_id=request.session_id,
        organization_id=organization_id,
        source=source,
        authoritative_revision=result.authoritative_revision,
        enrichment_cycle_id=cycle_id,
        previous=plan.constraint_evidence,
        _handled_candidate_ids=tuple(o.candidate_id for o in conflict.occurrences)
        if conflict and conflict.kind != "equivalent"
        else (),
        load_source_revision=lambda rid: repo.get_revision(
            request.session_id, rid, organization_id
        ),
    )
    states = advance_frontier(plan, result, record_id=record_id, result_kind="correction")
    offers = tuple(q for p in plans for q in p.questions)
    relevant = relevant_reoffers(
        plan,
        result,
        current,
        result.authoritative_revision,
        record_id=record_id,
        projected_states=states,
        offer_history=offers,
    )
    trigger = AcceptedResultTrigger(
        kind="correction",
        record_id=record_id,
        content_hash=result.content_hash,
        previous_plan_id=plan.plan_id,
        previous_plan_hash=plan.content_hash,
        message_id=message.message_id,
        message_content_sha256=hashlib.sha256(message.content.encode("utf-8")).hexdigest(),
    )
    next_plan = plan_f04(
        result.authoritative_revision,
        result.post_transition_evaluation,
        artifacts=service.artifacts,
        role_id=session.role_id,
        plan_id=plan_id,
        cycle_id=cycle_id,
        cycle_number=latest.cycle_number + 1,
        trigger=trigger,
        conflicts=(conflict,) if conflict else (),
        previous_plan=plan,
        current_states=states,
        constraint_evidence=constraints,
        offer_history=offers,
        relevant_changes=relevant,
    )
    return service._commit_verified(
        repo.commit_user_correction,
        lambda bound, record: (
            decode_correction_result(record.result_payload),
            get_current_state(bound, request.session_id, organization_id),
        ),
        correction_record_id=record_id,
        next_enrichment_cycle_id=cycle_id,
        session_id=request.session_id,
        organization_id=organization_id,
        expected_revision_id=current.revision_id,
        result_payload=result.model_dump(mode="json"),
        created_at=service._clock(),
        next_clarification_plan_id=plan_id,
        next_clarification_plan_payload=next_plan.model_dump(mode="json"),
    )


def _resume_intent_hash(scope, cause_id, request, message):
    return evidence_hash(
        dict(
            scope=scope,
            cause_id=cause_id,
            request=request.model_dump(mode="json"),
            source_message_sha256=hashlib.sha256(message.content.encode("utf-8")).hexdigest(),
        )
    )


def _resume_result(plan):
    trigger = plan.trigger
    questions = [
        q
        for q in plan.questions
        if q.cause_id == trigger.cause_id and q.offer_trigger == "explicit_resume"
    ]
    if len(questions) != 1:
        raise ValueError("Resume does not identify exactly one emitted question")
    payload = dict(
        schema_version="1.0.0",
        request_id=trigger.request_id,
        cause_id=trigger.cause_id,
        emitted_plan_id=plan.plan_id,
        emitted_plan_hash=plan.content_hash,
        emitted_question_id=questions[0].clarification_id,
        enrichment_cycle_id=plan.enrichment_cycle_id,
    )
    return ResumeResult(**payload, content_hash=evidence_hash(payload))


def _validate_resume_history(service, repo, session_id, organization_id, previous, plan, plans):
    trigger = plan.trigger
    message, _ = source_message(
        service, session_id, trigger.message_id, organization_id, repository=repo
    )
    request = ResumeRequest(
        schema_version="1.0.0",
        request_id=trigger.request_id,
        message_id=trigger.message_id,
        expected_revision_id=UUID(previous.design_revision_id),
        expected_enrichment_cycle_id=previous.enrichment_cycle_id,
        expected_enrichment_result_hash=previous.enrichment_result_hash,
        expected_clarification_plan_hash=previous.content_hash,
    )
    if trigger.request_hash != _resume_intent_hash(
        previous.scope, trigger.cause_id, request, message
    ):
        raise ValueError("Resume original source/CAS intent mismatch")
    states = {s.cause_id: s for s in previous.frontier_core.cause_states}
    cause = states.get(trigger.cause_id)
    if cause is None or (cause.status, cause.offer_state) != ("OPEN", "DORMANT"):
        raise ValueError("Resume origin was not dormant/open")
    states[trigger.cause_id] = cause.model_copy(update={"offer_state": "AVAILABLE"})
    if (
        plan.design_revision_id != previous.design_revision_id
        or plan.enrichment_result_hash != previous.enrichment_result_hash
        or plan.cause_definitions != previous.cause_definitions
        or tuple(states[k] for k in sorted(states)) != plan.frontier_core.cause_states
    ):
        raise ValueError("Resume changed canonical state or causal history")
    emitted = _resume_result(plan)
    question = next(q for q in plan.questions if q.clarification_id == emitted.emitted_question_id)
    old = max(
        (q.offer_ordinal for p in plans for q in p.questions if q.cause_id == trigger.cause_id),
        default=-1,
    )
    if question.offer_ordinal != old + 1:
        raise ValueError("Resume offer ordinal is not append-only")


@boundary
def resume_clarification(service, session_id, organization_id, cause_id, request):
    request = ResumeRequest.model_validate(request)
    session, current, cycles, plans, _, _ = _history(
        service, service.repository, session_id, organization_id
    )
    latest, plan = cycles[-1], plans[-1]
    message, _ = source_message(service, session_id, request.message_id, organization_id)
    intent_hash = _resume_intent_hash(plan.scope, cause_id, request, message)
    for old in plans:
        trigger = old.trigger
        if trigger.kind == "explicit_resume" and trigger.request_id == request.request_id:
            if trigger.request_hash != intent_hash:
                fail(Error.CLARIFICATION_CONFLICT, "Resume request already has a different intent")
            return _resume_result(old), get_current_state(service, session_id, organization_id)
    if request.expected_revision_id != current.revision_id:
        fail(Error.STALE_REVISION, "Product State changed before resume")
    if (
        request.expected_enrichment_cycle_id != latest.enrichment_cycle_id
        or request.expected_enrichment_result_hash != latest.result.content_hash
    ):
        fail(Error.ENRICHMENT_CYCLE_MISMATCH, "Enrichment frame changed before resume")
    if request.expected_clarification_plan_hash != plan.content_hash:
        fail(Error.STALE_CLARIFICATION_PLAN, "Clarification frame changed before resume")
    state = next((s for s in plan.frontier_core.cause_states if s.cause_id == cause_id), None)
    if state is None or (state.status, state.offer_state) != ("OPEN", "DORMANT"):
        fail(Error.CLARIFICATION_CONFLICT, "Cause is not eligible for explicit resume")
    definition = next(d for d in plan.cause_definitions if d.cause_id == cause_id)
    if protected_target(current, definition.target, plan.constraint_evidence):
        fail(Error.CLARIFICATION_CONFLICT, "Protected target cannot be re-offered")
    offers = tuple(q for p in plans for q in p.questions)
    if not any(q.cause_id == cause_id for q in offers):
        fail(Error.CLARIFICATION_CONFLICT, "Cause has no prior representable question")
    cycle_id, plan_id = service._uuid(), service._uuid()
    trigger = ResumeTrigger(
        kind="explicit_resume",
        request_id=request.request_id,
        request_hash=intent_hash,
        message_id=message.message_id,
        cause_id=cause_id,
        previous_plan_id=plan.plan_id,
        previous_plan_hash=plan.content_hash,
    )
    next_plan = plan_f04(
        current,
        latest.result,
        artifacts=service.artifacts,
        role_id=session.role_id,
        plan_id=plan_id,
        cycle_id=cycle_id,
        cycle_number=latest.cycle_number + 1,
        trigger=trigger,
        previous_plan=plan,
        current_states=plan.frontier_core.cause_states,
        constraint_evidence=plan.constraint_evidence,
        resume_cause_id=cause_id,
        offer_history=offers,
    )
    record = service.repository.commit_clarification_resume(
        session_id=session_id,
        organization_id=organization_id,
        request_payload=request.model_dump(mode="json"),
        request_hash=intent_hash,
        cause_id=cause_id,
        next_enrichment_cycle_id=cycle_id,
        next_enrichment_result=latest.result,
        next_clarification_plan_id=plan_id,
        next_clarification_plan_payload=next_plan.model_dump(mode="json"),
        created_at=service._clock(),
    )
    return _resume_result(
        ClarificationPlanV2.model_validate(record.plan_payload)
    ), get_current_state(service, session_id, organization_id)
