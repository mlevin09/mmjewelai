"""F04 scoped composition of the existing Parser/Matrix/Rules/clarification planner.

No canonical value is accepted here. Persisted results and revision/CAS are the
authority for lifecycle transitions; this module builds immutable planning evidence.
"""

import hashlib
from functools import partial

from jewelai_domain.clarification_state import (
    F04_PROFILE,
    ArtifactPins,
    InputContext,
    OccurrenceRef,
    ReleasePin,
    RuleRef,
    build_availability_overlay,
    evidence_hash,
)
from jewelai_domain.dictionary import DictionaryLocale
from jewelai_domain.lock_protection import locked_ancestor, state_fields
from jewelai_domain.rules import analyze_gaps
from jewelai_domain.rules_v2 import RuleContextV2
from jewelai_prompts.enrichment import StructuredPromptEnrichmentResultV2

from .clarification import (
    ClarificationCategory,
    ClarificationImportance,
    ClarificationOption,
    _question,
    _rule_question_from_plan,
    continue_clarification_plan,
    plan_clarifications,
)
from .clarification_answers import ClarificationDecision
from .clarification_v2 import (
    ClarificationOptionV2,
    ClarificationPlanV2,
    ClarificationQuestionV2,
    cause_definition,
    frontier_core,
    open_cause_state,
)
from .conflict_evidence import stable_id
from .parsed_enrichment import ParsedCandidateEnrichmentResultV2


def artifact_pins(artifacts, revision):
    hashes = dict(artifacts.artifact_hashes)
    if not all(name in hashes for name in ("dictionary", "questions", "rules")):
        raise ValueError("F04 requires exact trusted artifact byte hashes")
    return ArtifactPins(
        design_schema_version=revision.schema_version,
        role_artifact_version=artifacts.versions.roles,
        dictionary_artifact_version=artifacts.versions.dictionary,
        question_schema_version="2.0.0",
        question_artifact_version="2.0.0",
        rules_schema_version="2.0.0",
        rules_artifact_version="2.0.0",
        prompt_template_artifact_version=artifacts.versions.prompts,
        dictionary_sha256=hashes["dictionary"],
        question_sha256=hashes["questions"],
        rules_sha256=hashes["rules"],
    )


def input_context(scope, revision, cycle_id, cycle_number, artifacts, release_pin):
    return InputContext(
        scope=scope,
        contract_profile=F04_PROFILE,
        source_revision_id=revision.revision_id,
        source_revision_sha256=evidence_hash(revision),
        source_enrichment_cycle_id=cycle_id,
        source_enrichment_cycle_number=cycle_number,
        release_pin=ReleasePin(
            package_id=release_pin.package_id,
            artifact_version=release_pin.artifact_version,
            runtime_sha256=release_pin.runtime_sha256,
            validation_report_sha256=release_pin.validation_report_sha256,
        ),
        artifact_pins=artifact_pins(artifacts, revision),
    )


def f04_enrichment(result, *, revision, context):
    payload = result.model_dump(mode="json", exclude={"content_hash"})
    payload.update(
        enrichment_version="2.0.0",
        contract_profile=F04_PROFILE,
        scope=context.scope,
        context=context,
        availability_overlay=build_availability_overlay(revision, scope=context.scope),
    )
    return StructuredPromptEnrichmentResultV2(**payload, content_hash=evidence_hash(payload))


def f04_evaluation(evaluation, *, revision, context):
    payload = evaluation.model_dump(mode="python")
    payload["enrichment_result"] = f04_enrichment(
        evaluation.enrichment_result, revision=revision, context=context
    )
    return ParsedCandidateEnrichmentResultV2(**payload)


def canonical_target(revision, concrete_target, *, scope):
    overlay = build_availability_overlay(revision, scope=scope)
    entries = [e for e in overlay.entries if e.target.concrete_target == concrete_target]
    if len(entries) != 1:
        raise ValueError("Target does not resolve to one existing canonical owner")
    return entries[0].target


def target_state(revision, target):
    fields = state_fields(revision.design)
    path = tuple(target.concrete_target.split("."))
    if path not in fields:
        raise ValueError("Canonical target is unavailable")
    return fields[path]


def protected_target(revision, target, constraints=(), *, ordinary=True):
    fields = state_fields(revision.design)
    path = tuple(target.concrete_target.split("."))
    state = fields.get(path)
    return bool(
        locked_ancestor(fields, path) is not None
        or ordinary
        and getattr(state, "confirmed", False)
        or any(
            e.status == "active"
            and e.kind == "preservation"
            and e.canonical_target == target.concrete_target
            for e in constraints
        )
    )


def _rule_ref(rule, pins):
    return RuleRef(
        artifact_version="2.0.0",
        artifact_sha256=pins.rules_sha256,
        rule_id=rule.rule_id,
        rule_version=rule.rule_version,
    )


def plan_f04(
    revision,
    enrichment,
    *,
    artifacts,
    role_id,
    plan_id,
    cycle_id,
    cycle_number,
    trigger,
    conflicts=(),
    previous_plan=None,
    current_states=None,
    constraint_evidence=(),
    resume_cause_id=None,
    relevant_changes=None,
    offer_history=(),
    answered_ids=(),
):
    """Versioned plan writer around the shared deterministic planner and Rules2.

    All state changes supplied by answer/correction callers must subsequently be
    checked against committed records on restoration. Hashes alone are not proof.
    """
    parsed_evaluation = hasattr(enrichment, "parse_result")
    result = enrichment.enrichment_result if parsed_evaluation else enrichment
    locale = (
        enrichment.parse_result.requested_locale
        if parsed_evaluation
        else previous_plan.locale.value
    )
    context = result.context
    scope = context.scope
    pins = context.artifact_pins
    definitions = {d.cause_id: d for d in previous_plan.cause_definitions} if previous_plan else {}
    states = {
        s.cause_id: s
        for s in (
            current_states
            if current_states is not None
            else previous_plan.frontier_core.cause_states
            if previous_plan
            else ()
        )
    }
    retained_conflicts = (
        {c.conflict_id: c for c in previous_plan.conflicts} if previous_plan else {}
    )
    retained_conflicts.update((c.conflict_id, c) for c in conflicts)
    changes = relevant_changes or {}
    raw = artifacts.rules.evaluate(revision, role_id)

    def new_definition(target, kind, predicate, refs=(), conflict=None, rule=None):
        d = cause_definition(
            scope=scope,
            target=target,
            kind=kind,
            origin_cycle_id=cycle_id,
            origin_revision_id=revision.revision_id,
            origin_plan_id=plan_id,
            source_candidate_refs=refs,
            source_conflict_id=conflict,
            rule_ref=_rule_ref(rule, pins) if rule else None,
            release_pin=context.release_pin,
            artifact_pins=pins,
            resolution_predicate=predicate,
        )
        definitions[d.cause_id] = d
        return d

    for conflict in conflicts:
        if conflict.kind == "equivalent":
            continue
        refs = tuple(
            OccurrenceRef(
                message_id=o.message_id,
                candidate_id=o.candidate_id,
                message_content_sha256=o.message_content_sha256,
            )
            for o in conflict.occurrences
        )
        rule = artifacts.rules["ask_unresolved_product_body_material"]
        d = new_definition(
            conflict.target,
            "material_" + conflict.kind,
            dict(
                kind="material_choice",
                target="metal.material",
                offered_values=conflict.normalized_values,
                conflict_id=conflict.conflict_id,
            ),
            refs,
            conflict.conflict_id,
            rule,
        )
        protected = protected_target(revision, conflict.target, constraint_evidence)
        states[d.cause_id] = open_cause_state(
            d, criticality="BLOCKING", offer_state="PROTECTED" if protected else "AVAILABLE"
        )

    # Use actual existing gap analysis, not Unknown qualifiers or guessed requirements.
    for gap in analyze_gaps(
        revision, questions=artifacts.questions, required_targets=artifacts.rules.required_targets
    ):
        if not gap.required or gap.state == "satisfied":
            continue
        if any(
            d.kind == "information_gap"
            and d.target.concrete_target == gap.concrete_target
            and states[d.cause_id].status == "OPEN"
            for d in definitions.values()
        ):
            continue
        rule = next(
            (
                artifacts.rules[t.rule_id]
                for t in raw.trace
                if t.applicable and t.action_considered == "ask" and t.target == gap.target
            ),
            None,
        )
        if rule is None:
            # Roles/derivations retain their existing policy; no invented ask rule.
            continue
        target = canonical_target(revision, gap.concrete_target, scope=scope)
        d = new_definition(
            target,
            "information_gap",
            dict(
                kind="gap_satisfied",
                concrete_target=gap.concrete_target,
                original_gap_state=gap.state.value,
            ),
            rule=rule,
        )
        states[d.cause_id] = open_cause_state(
            d,
            criticality="BLOCKING",
            offer_state="PROTECTED"
            if protected_target(revision, target, constraint_evidence)
            else "AVAILABLE",
        )

    # Only a typed resume or a verified accepted dependency change releases dormancy.
    for cause_id, state in tuple(states.items()):
        if state.status != "OPEN":
            continue
        target = definitions[cause_id].target
        if protected_target(revision, target, constraint_evidence):
            states[cause_id] = state.model_copy(update={"offer_state": "PROTECTED"})
        elif state.offer_state == "DORMANT" and (
            cause_id == resume_cause_id or cause_id in changes
        ):
            states[cause_id] = state.model_copy(update={"offer_state": "AVAILABLE"})

    def current_context():
        return RuleContextV2(
            frontier_core=frontier_core(scope, revision, states.values()),
            cause_definitions=tuple(definitions[k] for k in sorted(definitions)),
        )

    presentation = artifacts.rules.clarification_decision(
        revision, role_id, unresolved_context=current_context()
    )
    source_message_id = None
    source_hash = (
        hashlib.sha256(enrichment.parse_result.original_text.encode("utf-8")).hexdigest()
        if parsed_evaluation
        else getattr(trigger, "message_content_sha256", None)
    )
    if trigger.kind == "initial":
        source_message_id = trigger.message_id
    elif parsed_evaluation and enrichment.parser_proposal.source.kind == "message":
        source_message_id = enrichment.parser_proposal.source.message_id

    def build_question(**payload):
        for key in ("options", "source_candidate_ids", "source_proposal_ids", "evidence"):
            payload.setdefault(key, ())
        payload.setdefault("subject", None)
        semantic = payload["semantic_question_id"]
        concrete = payload["target"].value
        if payload["category"] == ClarificationCategory.REQUIRED_INFORMATION:
            concrete = presentation.concrete_target or concrete
        elif concrete == "side_stones[*].quantity" and len(revision.design.side_stones) == 1:
            concrete = f"side_stones.{revision.design.side_stones[0].group_id}.quantity"
        target = canonical_target(revision, concrete, scope=scope)
        material = semantic == "METAL_MATERIAL"
        candidates = [
            d
            for d in definitions.values()
            if d.target == target
            and states[d.cause_id].status == "OPEN"
            and (
                d.kind.startswith("material_")
                if material
                else d.kind == "information_gap"
                if payload["category"] == ClarificationCategory.REQUIRED_INFORMATION
                else False
            )
        ]
        if candidates:
            d = min(candidates, key=lambda item: item.cause_id)
        else:
            refs = tuple(
                OccurrenceRef(
                    message_id=source_message_id, candidate_id=c, message_content_sha256=source_hash
                )
                for c in payload["source_candidate_ids"]
            )
            kind = (
                "knowledge_offer"
                if payload["category"] == ClarificationCategory.KNOWLEDGE_RECOMMENDATION
                else "preference_offer"
                if payload["category"] == ClarificationCategory.PREFERENCE_ACCEPTANCE
                else "unbound_request"
            )
            predicate = dict(
                kind="offer_decided",
                semantic_question_id=semantic,
                offered_values=tuple(o.value for o in payload["options"]),
                source_occurrence_refs=refs,
            )
            existing = next(
                (
                    v
                    for v in definitions.values()
                    if v.target == target
                    and v.kind == kind
                    and evidence_hash(v.resolution_predicate) == evidence_hash(predicate)
                ),
                None,
            )
            d = existing or new_definition(target, kind, predicate, refs)
            if d.cause_id not in states:
                states[d.cause_id] = open_cause_state(
                    d, criticality="NONBLOCKING", offer_state="AVAILABLE"
                )
        return question_for_cause(d, payload)

    def question_for_cause(d, payload):
        templates = tuple(offer_history) + (previous_plan.questions if previous_plan else ())
        old = max(
            (q for q in templates if q.cause_id == d.cause_id),
            key=lambda q: q.offer_ordinal,
            default=None,
        )
        ordinal = old.offer_ordinal if old else 0
        # History may contain a dormant offer no longer present in the latest plan.
        # Its ordinal is retained in the typed caller-supplied resume trigger metadata.
        if resume_cause_id == d.cause_id or d.cause_id in changes:
            ordinal += 1
        offer_trigger = (
            "explicit_resume"
            if resume_cause_id == d.cause_id
            else "relevant_change"
            if d.cause_id in changes
            else old.offer_trigger
            if old
            else "initial"
        )
        trigger_ref = (
            trigger
            if resume_cause_id == d.cause_id
            else changes[d.cause_id]
            if d.cause_id in changes
            else old.trigger_ref
            if old
            else trigger
        )
        options = payload["options"]
        option_seeds = []
        if d.kind.startswith("material_"):
            conflict = retained_conflicts[d.source_conflict_id]
            options = []
            for value in conflict.normalized_values:
                entry = artifacts.dictionary[value]
                refs = tuple(
                    OccurrenceRef(
                        message_id=o.message_id,
                        candidate_id=o.candidate_id,
                        message_content_sha256=o.message_content_sha256,
                    )
                    for o in conflict.occurrences
                    if o.normalized_dictionary_id == value
                )
                options.append(
                    ClarificationOption(
                        value=value,
                        label=entry.canonical_terms.for_locale(DictionaryLocale(locale)),
                        source_ids=(),
                    )
                )
                option_seeds.append(dict(value=value, source_occurrence_refs=refs))
        else:
            for option in options:
                refs = tuple(
                    ref for ref in d.source_candidate_refs if ref.candidate_id in option.source_ids
                )
                option_seeds.append(dict(value=option.value, source_occurrence_refs=refs))
        identity = dict(
            scope=scope,
            cause_id=d.cause_id,
            offer_ordinal=ordinal,
            offer_trigger=offer_trigger,
            trigger_fingerprint=evidence_hash(trigger_ref),
            revision_id=revision.revision_id,
            release_pin=context.release_pin,
            artifact_pins=pins,
            semantic_question_id=payload["semantic_question_id"],
            source_occurrence_refs=d.source_candidate_refs,
            option_seeds=option_seeds,
        )
        question_id = stable_id("clarification_", "jewelai.f04.question/2.0.0", identity)
        typed = []
        for option, seed in sorted(
            zip(options, option_seeds, strict=True), key=lambda pair: pair[0].value
        ):
            typed.append(
                ClarificationOptionV2(
                    option_id=stable_id(
                        "option_",
                        "jewelai.f04.option/1.0.0",
                        dict(
                            question_id=question_id,
                            value=option.value,
                            dictionary_category=artifacts.dictionary[option.value].category,
                            dictionary_artifact_version=pins.dictionary_artifact_version,
                            dictionary_sha256=pins.dictionary_sha256,
                        ),
                    ),
                    value=option.value,
                    label=option.label,
                    source_occurrence_refs=seed["source_occurrence_refs"],
                )
            )
        if (
            states[d.cause_id].criticality == "NONBLOCKING"
            and payload["importance"] == ClarificationImportance.BLOCKING
        ):
            payload["importance"] = (
                ClarificationImportance.OPTIONAL
                if d.kind in {"preference_offer", "knowledge_offer"}
                else ClarificationImportance.RECOMMENDED
            )
        payload.update(
            clarification_id=question_id,
            target=d.target,
            options=tuple(typed),
            cause_id=d.cause_id,
            conflict_id=d.source_conflict_id,
            offer_ordinal=ordinal,
            offer_trigger=offer_trigger,
            trigger_ref=trigger_ref,
            contract_profile=F04_PROFILE,
            source_plan_id=plan_id,
            allowed_decisions=(
                ClarificationDecision.SELECT_OPTION,
                ClarificationDecision.SKIP,
                ClarificationDecision.UNKNOWN,
            )
            if d.kind.startswith("material_")
            else (
                ClarificationDecision.SELECT_OPTION,
                ClarificationDecision.ACCEPT,
                ClarificationDecision.REJECT,
                ClarificationDecision.SKIP,
                ClarificationDecision.UNKNOWN,
            )
            if d.kind in {"preference_offer", "knowledge_offer"}
            else (
                ClarificationDecision.SELECT_OPTION,
                ClarificationDecision.SKIP,
                ClarificationDecision.UNKNOWN,
            ),
        )
        if d.kind.startswith("material_"):
            template = artifacts.questions.render("METAL_MATERIAL", role_id, locale).wording
            payload["text"] = template.format(
                options=(" или " if locale == "ru" else " or ").join(o.label for o in typed)
            )
            payload["category"] = ClarificationCategory.MATERIAL_AMBIGUITY
            payload["importance"] = ClarificationImportance.BLOCKING
            payload["source_candidate_ids"] = tuple(
                ref.candidate_id for ref in d.source_candidate_refs
            )
            conflict = retained_conflicts[d.source_conflict_id]
            from .clarification import ClarificationEvidence

            payload["evidence"] = tuple(
                ClarificationEvidence(
                    candidate_id=o.candidate_id,
                    start=o.evidence_start,
                    end=o.evidence_end,
                    text=o.evidence_text,
                )
                for o in conflict.occurrences
            )
        return ClarificationQuestionV2(**payload)

    def finish_plan(**payload):
        offered = {q.cause_id: q for q in payload["questions"]}
        # Preserve unanswered optional/material offers not repeated by the new parse.
        if previous_plan:
            for old in tuple(offer_history) + previous_plan.questions:
                if (
                    old.cause_id in offered
                    or states[old.cause_id].status != "OPEN"
                    or states[old.cause_id].offer_state != "AVAILABLE"
                ):
                    continue
                p = old.model_dump(mode="python")
                p["design_revision_id"] = str(revision.revision_id)
                p["options"] = tuple(
                    ClarificationOption(
                        value=o.value,
                        label=o.label,
                        source_ids=tuple(r.candidate_id for r in o.source_occurrence_refs),
                    )
                    for o in old.options
                )
                offered[old.cause_id] = question_for_cause(definitions[old.cause_id], p)
        # Dormancy and protection affect presentation, never erase current blockers.
        payload["questions"] = tuple(
            sorted(
                (
                    q
                    for cid, q in offered.items()
                    if states[cid].status == "OPEN" and states[cid].offer_state == "AVAILABLE"
                ),
                key=lambda q: (-int(q.importance == "blocking"), -q.priority, q.clarification_id),
            )
        )
        core = current_context().frontier_core
        payload.update(
            plan_version="2.0.0",
            contract_profile=F04_PROFILE,
            scope=scope,
            plan_id=plan_id,
            enrichment_cycle_id=cycle_id,
            enrichment_cycle_number=cycle_number,
            enrichment_result_hash=result.content_hash,
            revision_sha256=evidence_hash(revision),
            artifact_pins=pins,
            conflicts=tuple(retained_conflicts[k] for k in sorted(retained_conflicts)),
            cause_definitions=tuple(definitions[k] for k in sorted(definitions)),
            frontier_core=core,
            trigger=trigger,
            rule_decision=artifacts.rules.evaluate(
                revision, role_id, unresolved_context=current_context()
            ),
            can_continue_without_answers=not any(s.blocks_current for s in states.values()),
        )
        payload.pop("content_hash", None)
        if payload["rule_decision"].decision == "block":
            payload["can_continue_without_answers"] = False
        return ClarificationPlanV2(**payload, content_hash=evidence_hash(payload))

    if not parsed_evaluation:

        def rebind(old, revision_id):
            p = old.model_dump(mode="python")
            p["design_revision_id"] = str(revision_id)
            p["options"] = tuple(
                ClarificationOption(
                    value=o.value,
                    label=o.label,
                    source_ids=tuple(r.candidate_id for r in o.source_occurrence_refs),
                )
                for o in old.options
            )
            return question_for_cause(definitions[old.cause_id], p)

        return continue_clarification_plan(
            previous_plan,
            revision,
            answered_clarification_ids=answered_ids,
            questions=artifacts.questions,
            rules=artifacts.rules,
            _plan_reader=ClarificationPlanV2,
            _plan_builder=finish_plan,
            _rebind_builder=rebind,
            _question_builder=partial(_rule_question_from_plan, _model_type=build_question),
            _rule_decision_override=presentation,
        )
    return plan_clarifications(
        revision,
        enrichment,
        role_id=role_id,
        dictionary=artifacts.dictionary,
        questions=artifacts.questions,
        rules=artifacts.rules,
        constraint_evidence=constraint_evidence,
        _question_builder=partial(_question, _model_type=build_question),
        _plan_builder=finish_plan,
        _unresolved_context=current_context(),
        _rule_decision_override=presentation,
    )
