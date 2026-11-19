"""US-01 first-turn SO functions; one canonical State, untrusted model proposals.

No clarification/coverage/IFP workflow is started here. Legacy first-turn1 and its
recorded Parser governance remain intact. Network work occurs outside repository
transactions; a write-once delivered reply is distinct from the committed input.
"""

import hashlib
import json
import re
from copy import copy
from datetime import UTC
from types import SimpleNamespace
from typing import Annotated, Literal
from uuid import UUID

from jewelai_domain.clarification_state import StrictEvidenceModel, evidence_hash
from jewelai_domain.knowledge_policy import RuntimeProvenance, RuntimeSemanticState
from jewelai_domain.knowledge_runtime import bind_verified_release
from jewelai_domain.models import Explicit, KnownValue, MessageSource
from jewelai_domain.revisions import revise_design
from jewelai_parser import parse_full_message
from jewelai_prompts import EnrichmentProposal, enrich_prompt_with_active_release
from jewelai_prompts.final_prompt import FinalPromptDesignFact
from jewelai_prompts.review_description import render_review_description
from jewelai_prompts.revision_projection import project_revision
from pydantic import Field, StringConstraints, model_validator

from .conversation_model import ConversationContext
from .first_turn import CreationFact
from .semantic_proposal import ArbitrationDecision, SemanticProposal, arbitrate

CONTRACT = "jewelai.us01.first-turn/2.0.0"
SEMANTIC_VERSION = "jewelai.us01.meaning/1.0.0"
REPLY_VERSION = "jewelai.us01.reply/1.0.0"
RawText = Annotated[str, StringConstraints(strict=True, max_length=2000)]


class ProductSelection(StrictEvidenceModel):
    target: Literal["jewelry_type"] = "jewelry_type"
    value: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,79}$")]


class TranscriptSource(StrictEvidenceModel):
    kind: Literal["editable_transcript"]
    user_edited: bool


class NaturalTurnRequest(StrictEvidenceModel):
    schema_version: Literal["2.0.0"]
    turn_id: UUID
    expected_revision_id: UUID
    original_text: RawText = ""
    selections: tuple[ProductSelection, ...] = Field(default=(), max_length=1)
    transcript: TranscriptSource | None = None

    @model_validator(mode="after")
    def valid_input(self):
        if not self.original_text.strip() and not self.selections:
            raise ValueError("First turn requires text or a typed product selection")
        if self.transcript and not self.original_text.strip():
            raise ValueError("Transcript provenance requires actual editable text")
        return self


class SemanticObservation(StrictEvidenceModel):
    source_ref: str
    kind: Literal["term", "stone", "count", "unresolved"]
    text: str
    start: int
    end: int
    normalized_values: tuple[str, ...] = ()
    count: int | None = None
    attachment: None = None
    quantity_scope: None = None
    classification: str


def _hash_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def product_options(runtime, locale):
    """Only qualified compiled product terminology; never a hand-written UI enum."""
    concepts = {c.concept_id for c in runtime.domain_knowledge if c.kind == "jewelry_type"}
    return tuple(
        {"value": m.concept_id, "label": m.canonical_term, "mapping_id": m.mapping_id}
        for m in sorted(runtime.language_mappings, key=lambda m: m.mapping_id)
        if m.concept_id in concepts and m.locale == locale and m.mapping_mode == "DIRECT"
    )


def source_evidence(request, parsed, runtime, locale):
    """Recognized terms/counts are evidence, not automatically addressable stone groups."""
    observations = []
    for c in parsed.candidates if parsed else ():
        span = c.evidence
        stone = any(
            k.concept_id in c.normalized_values and k.kind == "gemstone_material"
            for k in runtime.domain_knowledge
        )
        observations.append(
            SemanticObservation(
                source_ref=c.candidate_id,
                kind="stone" if stone else "term" if c.normalized_values else "unresolved",
                text=span.text,
                start=span.start,
                end=span.end,
                normalized_values=c.normalized_values,
                classification=c.classification.value,
            )
        )
    # Bounded count normalization of actual raw spans only. It does not reuse a
    # Parser's center/side hint as attachment or guess EACH/PAIR/TOTAL.
    numbers = {
        "two": 2,
        "двумя": 2,
        "два": 2,
        "две": 2,
        "three": 3,
        "тремя": 3,
        "три": 3,
        "four": 4,
        "четырьмя": 4,
        "четыре": 4,
    }
    for match in re.finditer(
        r"\b(?:two|three|four|двумя|два|две|тремя|три|четырьмя|четыре|[2-4])\b",
        request.original_text,
        re.I,
    ):
        following = [o for o in observations if o.kind == "stone" and o.start >= match.end()]
        if not following or request.original_text[match.end() : following[0].start].strip():
            continue
        word = match.group().casefold()
        observations.append(
            SemanticObservation(
                source_ref=f"count:{match.start()}:{match.end()}",
                kind="count",
                text=match.group(),
                start=match.start(),
                end=match.end(),
                count=int(word) if word.isdigit() else numbers[word],
                classification=following[0].classification,
            )
        )
    choices = {o["value"]: o for o in product_options(runtime, locale)}
    for index, selection in enumerate(request.selections):
        if selection.value not in choices:
            raise ValueError("Product selection is not in the qualified release")
        observations.append(
            SemanticObservation(
                source_ref=f"selection:{index}",
                kind="term",
                text="",
                start=0,
                end=0,
                normalized_values=(selection.value,),
                classification="requirement",
            )
        )
    return tuple(observations)


def decided_facts(meaning, decisions):
    accepted = {d.proposal_id: d for d in decisions if d.outcome == "ACCEPT"}
    return tuple(
        CreationFact(
            target=c.target,
            value=str(c.value),
            candidate_id=c.proposal_id,
            start=accepted[c.proposal_id].source_span.start
            if accepted[c.proposal_id].source_span
            else 0,
            end=accepted[c.proposal_id].source_span.end
            if accepted[c.proposal_id].source_span
            else 0,
            text=accepted[c.proposal_id].source_span.text
            if accepted[c.proposal_id].source_span
            else "",
            mapping_ids=accepted[c.proposal_id].mapping_ids,
        )
        for c in meaning.changes
        if c.proposal_id in accepted
    )


def matrix_transition(service, parent, source, facts, verified):
    """The model can veto/qualify source-backed candidates, never add a value."""
    proposals = tuple(
        EnrichmentProposal(
            target=f.target,
            value=f.value,
            source_id=f.candidate_id,
            semantic_state=RuntimeSemanticState.NORMALIZED,
            provenance=RuntimeProvenance.NORMALIZED_FROM_USER,
        )
        for f in facts
    )
    matrix = enrich_prompt_with_active_release(
        parent,
        service.artifacts.prompts,
        service.artifact_store,
        knowledge_package_id=verified.package_id,
        knowledge_artifact_version=str(verified.artifact_version),
        active_release=service.active_release,
        validation_report=service.validation_report,
        proposals=proposals,
    )
    payload = parent.design.model_dump(mode="json")
    for decision in matrix.decisions:
        if decision.outcome != "APPLIED":
            continue
        keys = decision.target.split(".")
        old = parent.design
        dest = payload
        for key in keys[:-1]:
            old = getattr(old, key)
            dest = dest[key]
        current = getattr(old, keys[-1])
        if isinstance(current, KnownValue):
            if current.value != decision.result.value:
                raise ValueError("Initial conversation cannot replace existing accepted values")
            continue  # Compatible facts retain original provenance/confirmation/locks.
        if current is not None and (current.locked or current.confirmed):
            continue
        dest[keys[-1]] = Explicit[str](value=decision.result.value, source=source).model_dump(
            mode="json"
        )
    design = type(parent.design).model_validate(payload)
    return design, matrix


def matrix_arbitration(decisions, matrix):
    blocked = {d.proposal.source_id for d in matrix.decisions if d.outcome == "BLOCKED"}
    return tuple(
        d.model_copy(update={"outcome": "NO_COMMIT", "reason": "matrix_blocked"})
        if d.outcome == "ACCEPT" and d.proposal_id in blocked
        else d
        for d in decisions
    )


def current_brief(service, revision, locale, runtime):
    """Reuse canonical projection and existing readable rendering; no final handoff."""
    projection = project_revision(revision)
    facts = tuple(
        FinalPromptDesignFact(
            target=e.concrete_target,
            applicability=e.applicability,
            value=e.value,
            origin=e.origin,
            confirmed=e.confirmed,
            locked=e.locked,
            semantic_state=RuntimeSemanticState.EXPLICIT,
            provenance=RuntimeProvenance.USER_EXPLICIT_LATEST,
            source_ids=(),
        )
        for e in projection.specification_entries
    )
    snapshot = SimpleNamespace(
        locale=locale,
        enrichment_result=SimpleNamespace(availability_overlay=None),
        constraint_evidence=(),
    )

    class QualifiedTerms:
        def __getitem__(self, concept_id):
            try:
                return service.artifacts.dictionary[concept_id]
            except KeyError:
                # Presentation-only qualified terminology, not a new Dictionary
                # artifact, inference rule or authority to accept a parameter.
                def for_locale(requested):
                    terms = {
                        m.canonical_term
                        for m in runtime.language_mappings
                        if m.concept_id == concept_id
                        and m.locale == requested.value
                        and m.mapping_mode == "DIRECT"
                    }
                    if len(terms) != 1:
                        raise KeyError(concept_id)
                    return next(iter(terms))

                return SimpleNamespace(canonical_terms=SimpleNamespace(for_locale=for_locale))

    return render_review_description(snapshot, facts, (), (), dictionary=QualifiedTerms()).text


def reply_options(brief, observations, locale):
    """Explicit fallback wording from State and retained source-only evidence.

    This is not the successful model path or a menu for model selection. The
    adapter authors new natural wording, checked separately by checked_reply.
    """
    ru = locale == "ru"
    unresolved = [o for o in observations if o.kind in {"stone", "count", "unresolved"}]
    note = ""
    if unresolved:
        terms = ", ".join(dict.fromkeys("«" + o.text + "»" for o in unresolved))
        qualifier = (
            (
                "Расположение камней и распределение количества пока не определены."
                if ru
                else "Stone attachment and quantity scope remain unresolved."
            )
            if any(o.kind in {"stone", "count"} for o in unresolved)
            else ""
        )
        note = (
            f"Вы также упомянули {terms}. "
            f"Эти сведения сохранены отдельно и не приняты как параметры. {qualifier}"
            if ru
            else f"You also mentioned {terms}. "
            f"These details are retained separately, not accepted as parameters. {qualifier}"
        ).strip()
    openings = (
        ("Понял ваш замысел.", "Спасибо, начнём с сохранённых деталей.")
        if ru
        else ("I understand your idea.", "Thanks, let's start with the details you provided.")
    )
    degraded = (
        "Резервный ответ без языковой модели." if ru else "Fallback reply without a language model."
    )
    return tuple(
        "\n\n".join(s for s in (degraded, opening, brief, note) if s) for opening in openings
    )


def checked_reply(
    draft,
    options,
    *,
    service=None,
    revision=None,
    runtime=None,
    locale=None,
    observations=(),
    expected_model=None,
):
    """Critical fact checking, not a neutral-word vocabulary or template selector.

    Free conversational wording is retained. The current independent Parser and
    explicit raw quantity evidence check jewelry claims and component ownership;
    unseen values, false saved claims and unsupported numeric allocations fail
    closed. This bounded check is not general professional-advice qualification.
    """
    from jewelai_parser.full_message import (
        _parse_recorded_message,
        _sentence_bounds,
        _source_governance,
    )

    from .conversation_model import UntrustedConversationDraft

    if (
        not isinstance(draft, UntrustedConversationDraft)
        or not 1 <= len(draft.text) <= 6000
        or draft.provider != "qwen"
        or draft.prompt_version != REPLY_VERSION
        or expected_model is not None
        and draft.model != expected_model
    ):
        raise ValueError("Model reply provenance/size mismatch")
    if service is None or revision is None:
        raise ValueError("Reply requires actual committed State")
    parsed = _parse_recorded_message(
        draft.text,
        parse_version="1.3.0",
        locale=locale,
        dictionary=service.artifacts.dictionary,
        knowledge_runtime=runtime,
    )
    known = {
        e.concrete_target: e
        for e in project_revision(revision).specification_entries
        if e.applicability == "value"
    }
    mentions = {v for o in observations for v in o.normalized_values}
    counts = {o.count for o in observations if o.kind == "count"}
    # A generic "everything was saved" claim cannot be verified by checking
    # only the three writable initial targets. Stone/count observations remain
    # unresolved in US-01 even when the jewelry/body-metal facts are committed.
    unresolved_source = any(o.kind in {"stone", "count", "unresolved"} for o in observations)
    if unresolved_source:
        for sentence in re.split(r"(?<=[.!?])\s+|\n", draft.text):
            if "?" in sentence:
                continue
            sweeping = re.search(
                r"\b(?:all|every|everything|все|всё|вс[её]\b|кажд\w*)\b",
                sentence, re.I,
            )
            saved_claim = re.search(
                r"\b(?:saved|accepted|selected|recorded|сохран\w*|принят\w*|выбран\w*|записан\w*)\b",
                sentence, re.I,
            )
            denial = re.search(
                r"\b(?:not|never|не|никогда)\b", sentence, re.I,
            )
            if sweeping and saved_claim and not denial:
                raise ValueError("Reply globally claims unresolved source facts were saved")
    covered = []
    acknowledged = set()
    for c in parsed.candidates:
        if not c.normalized_values and c.raw_value is None:
            continue
        if (
            c.target is None
            and c.normalized_values
            and any(
                other.target is not None
                and other.evidence == c.evidence
                and other.normalized_values == c.normalized_values
                for other in parsed.candidates
            )
        ):
            continue  # Generic lexical duplicate; the owned candidate is checked below.
        with _source_governance("1.3.0"):
            left, right = _sentence_bounds(draft.text, c.evidence.start, c.evidence.end)
        sentence = draft.text[left:right]
        questioned = (
            draft.text[right : right + 1] == "?"
            or "?" in sentence
            or bool(
                re.match(
                    r"\s*(?:как|сколько|какие|какой|how|which|are|is|should)\b", sentence, re.I
                )
            )
        )
        uncertain = questioned or bool(
            re.search(
                r"\b(?:unresolved|unconfirmed|unclear|not yet|not saved|not accepted|mentioned|"
                r"request includes|request mentions|уточн\w*|не определ\w*|не сохран\w*|"
                r"не принят\w*|упомян\w*)\b",
                sentence,
                re.I,
            )
        )
        if c.normalized_values:
            entry = known.get(str(c.target))
            committed = entry is not None and tuple(c.normalized_values) == (entry.value,)
            if committed:
                if c.classification == "prohibition" and not questioned:
                    raise ValueError("Reply contradicts committed State")
                if not questioned:
                    acknowledged.add(str(c.target))
            else:
                # A source reference is not a commitment. "Mentioned" or a
                # nearby question cannot authorize a false saved/selected claim.
                claimed_commit = any(
                    not re.search(r"\b(?:not|never|не)\s+(?:yet\s+)?$", sentence[: m.start()], re.I)
                    for m in re.finditer(
                        r"\b(?:saved|accepted|selected|recorded|сохран\w*|принят\w*|выбран\w*|записан\w*)\b",
                        sentence,
                        re.I,
                    )
                )
                if claimed_commit or not (uncertain and set(c.normalized_values) <= mentions):
                    raise ValueError("Reply asserts uncommitted or ungrounded jewelry facts")
        elif c.raw_value is not None and isinstance(c.raw_value, (int, float, dict)):
            # Structured measurements are not unallocated stone counts. The
            # initial slice cannot turn source mentions into saved dimensions,
            # weights or professional estimates, even if a count is also two.
            if isinstance(c.raw_value, dict) or not uncertain or c.raw_value not in counts:
                raise ValueError("Reply invents a measurement or quantity allocation")
        covered.append((c.evidence.start, c.evidence.end))
    # Any bare numeric claim must be backed by retained source quantity and
    # explicitly unresolved/questioned. No inferred weights, units or dimensions.
    for m in re.finditer(r"(?<!\w)\d+(?:[.,]\d+)?", draft.text):
        if not any(a <= m.start() < m.end() <= b for a, b in covered):
            with _source_governance("1.3.0"):
                left, right = _sentence_bounds(draft.text, m.start(), m.end())
            if (
                float(m.group().replace(",", ".")) not in counts
                or "?" not in draft.text[left : right + 1]
            ):
                raise ValueError("Reply contains unchecked numeric facts")
    if counts and not any(o.kind == "stone" for o in observations):
        raise ValueError("Unresolved count lost its source entity")
    required = {
        target for target in known if target in {"jewelry_type", "metal.material", "metal.color"}
    }
    if not required <= acknowledged:
        raise ValueError("Reply does not acknowledge the actual committed critical facts")
    for sentence in re.split(r"(?<=[.!?])\s+|\n", draft.text):
        if "?" in sentence:
            continue
        if re.search(r"\b(?:unlocked|разблокир\w*)\b", sentence, re.I):
            raise ValueError("An initial reply cannot claim to revoke protection")
        if re.search(r"\b(?:locked|заблокир\w*)\b", sentence, re.I) and not (
            required and all(known[t].locked for t in required)
        ):
            raise ValueError("Reply claims protection absent from committed State")
        if re.search(r"\b(?:confirmed|подтвержд[её]н\w*)\b", sentence, re.I) and not (
            required and all(known[t].confirmed for t in required)
        ):
            raise ValueError("Reply claims confirmation absent from committed State")
    if counts:
        if not re.search(
            r"\b(?:pair|each|total|allocat\w*|scope|распред\w*|пару|кажд\w*|всего)\b",
            draft.text,
            re.I,
        ):
            raise ValueError("Reply did not address the unresolved quantity scope")
        # A question about EACH/PAIR/TOTAL is fine; affirming an allocation is
        # not. A question elsewhere in the reply cannot qualify this sentence.
        for sentence in re.split(r"(?<=[.!?])\s+|\n", draft.text):
            if re.search(r"\b(?:each|per|every|total|кажд\w*|всего)\b", sentence, re.I):
                if "?" not in sentence:
                    raise ValueError("Reply asserts an unresolved quantity scope")
    # With unresolved stone scope, a response must actually ask/retain uncertainty;
    # it cannot silently present a guessed distribution as an accepted design.
    if any(o.kind in {"stone", "count"} for o in observations) and not re.search(
        r"\?|\b(?:unresolved|unclear|уточн\w*|не определ\w*)\b", draft.text, re.I
    ):
        raise ValueError("Reply omitted consequential source uncertainty")
    return draft


class NaturalTurnRead(StrictEvidenceModel):
    schema_version: Literal["2.0.0"] = "2.0.0"
    commit_status: Literal["committed"] = "committed"
    delivery_status: Literal["pending", "delivered"]
    evidence: dict
    input_hash: str
    delivered_reply: dict | None
    current_revision: dict
    current_brief: str
    is_current_revision: bool


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _context(
    session,
    message_id,
    request,
    revision,
    parsed,
    binding,
    observations,
    *,
    turn_binding=None,
    options=(),
    meaning=None,
    decisions=(),
):
    return ConversationContext(
        message_id=message_id,
        original_text=request.original_text,
        locale=session.locale,
        role_id=session.role_id,
        committed_revision_json=revision.model_dump_json(),
        source_parse_json=_json(parsed.model_dump(mode="json") if parsed else None),
        knowledge_binding_json=binding.model_dump_json(),
        turn_binding_json=_json(turn_binding or {}),
        semantic_evidence_json=_json(
            {
                "observations": [o.model_dump(mode="json") for o in observations],
                "typed_selections": [s.model_dump(mode="json") for s in request.selections],
                "meaning": meaning.model_dump(mode="json") if meaning is not None else None,
                "decisions": [d.model_dump(mode="json") for d in decisions],
            }
        ),
        safe_reply_options_json=_json(options),
    )


def input_options(service, sid, oid, *, model_configured=False):
    bound = service._for_session(sid, oid)
    if not bound._is_f04:
        raise ValueError("US-01 requires retained F artifacts")
    session = bound.repository.get_design_session(sid, oid)
    runtime = bound._load_release()
    return {
        "schema_version": "2.0.0",
        "model_configured": model_configured,
        "locale": session.locale,
        "options": product_options(runtime.compiled_runtime, session.locale),
    }


def _evaluate_record(service, repo, sid, oid, record):
    """Replay one retained source/Matrix proof, not a model or entire chat history."""
    from jewelai_parser.full_message import _parse_recorded_message
    from jewelai_persistence import EnrichmentIntegrityError

    p = record["input"]
    try:
        if p["contract_version"] != CONTRACT:
            raise ValueError("Unsupported US-01 contract")
        request = NaturalTurnRequest.model_validate(p["request"])
        session = repo.get_design_session(sid, oid)
        parent = repo.get_revision(sid, request.expected_revision_id, oid)
        result = repo.get_revision(sid, UUID(p["result_revision_id"]), oid)
        message = repo.get_message(sid, UUID(p["message_id"]), oid)
        if (
            message.content != request.original_text
            or message.actor != "user"
            or p["message_sha256"] != _hash_text(message.content)
        ):
            raise ValueError("Raw source mismatch")
        if (
            p["role_id"] != session.role_id
            or p["locale"] != session.locale
            or p["parent_hash"] != evidence_hash(parent)
            or p["result_hash"] != evidence_hash(result)
        ):
            raise ValueError("Revision or session provenance mismatch")
        verified = service._load_release()
        binding = bind_verified_release(
            service.artifact_store,
            verified.package_id,
            str(verified.artifact_version),
            active_release=service.active_release,
            validation_report=service.validation_report,
        )
        if binding.model_dump(mode="json") != p["knowledge_binding"]:
            raise ValueError("Pinned Knowledge release mismatch")
        parsed = (
            _parse_recorded_message(
                message.content,
                parse_version="1.3.0",
                locale=session.locale,
                dictionary=service.artifacts.dictionary,
                knowledge_runtime=verified.compiled_runtime,
            )
            if message.content.strip()
            else None
        )
        if p["parsed"] != (parsed.model_dump(mode="json") if parsed else None):
            raise ValueError("Recorded Parser evidence mismatch")
        observed = source_evidence(request, parsed, verified.compiled_runtime, session.locale)
        if [o.model_dump(mode="json") for o in observed] != p["observations"]:
            raise ValueError("Source meaning evidence mismatch")
        meaning = SemanticProposal.model_validate(p["meaning"])
        decisions = arbitrate(
            meaning,
            text=request.original_text,
            parsed=parsed,
            revision=parent,
            dictionary=service.artifacts.dictionary,
            runtime=verified.compiled_runtime,
            locale=session.locale,
            selections=request.selections,
        )
        facts = decided_facts(meaning, decisions)
        if [f.model_dump(mode="json") for f in facts] != p["eligible_facts"]:
            raise ValueError("SO arbitration or source authority mismatch")
        source = MessageSource(
            message_id=str(message.message_id),
            recorded_at=message.created_at.replace(tzinfo=UTC)
            if message.created_at.tzinfo is None
            else message.created_at,
        )
        design, matrix = matrix_transition(service, parent, source, facts, verified)
        decisions = matrix_arbitration(decisions, matrix)
        if [d.model_dump(mode="json") for d in decisions] != p["arbitration"]:
            raise ValueError("Final SO/Matrix decision mismatch")
        if design != result.design or p["matrix"] != matrix.model_dump(mode="json"):
            raise ValueError("Matrix/State mismatch")
        if result.revision_id != parent.revision_id and (
            result.parent_revision_id != parent.revision_id or result.event.source != source
        ):
            raise ValueError("Source ancestry mismatch")
        if result.revision_id == parent.revision_id and design != parent.design:
            raise ValueError("Uncommitted proposed State")
        return session, request, result, parsed, binding, observed, verified
    except (ValueError, KeyError, TypeError) as exc:
        raise EnrichmentIntegrityError("US-01 source/State verification failed") from exc


def read(service, sid, oid):
    from jewelai_persistence import EnrichmentIntegrityError

    with service.repository.read_enrichment_history(sid, oid) as repo:
        record = repo.get_initial_conversation_turn(sid, oid)
        session, request, revision, parsed, binding, observed, verified = _evaluate_record(
            service, repo, sid, oid, record
        )
        original_brief = current_brief(service, revision, session.locale, verified.compiled_runtime)
        options = reply_options(original_brief, observed, session.locale)
        context = _context(
            session,
            UUID(record["input"]["message_id"]),
            request,
            revision,
            parsed,
            binding,
            observed,
            turn_binding={
                "input_hash": record["input_hash"],
                "revision_id": str(revision.revision_id),
                "revision_hash": evidence_hash(revision),
            },
            options=options,
            meaning=SemanticProposal.model_validate(record["input"]["meaning"]),
            decisions=tuple(
                ArbitrationDecision.model_validate(d) for d in record["input"]["arbitration"]
            ),
        )
        reply = record["reply"]
        if reply is not None:
            if (
                set(reply)
                != {
                    "contract_version",
                    "origin",
                    "text",
                    "provider",
                    "model",
                    "prompt_version",
                    "context_hash",
                    "input_hash",
                    "revision_id",
                    "failure_code",
                }
                or reply["contract_version"] != REPLY_VERSION
                or reply["input_hash"] != record["input_hash"]
                or reply["revision_id"] != str(revision.revision_id)
                or reply["context_hash"] != evidence_hash(context.__dict__)
            ):
                raise EnrichmentIntegrityError("US-01 delivered reply provenance/claims mismatch")
            if reply["origin"] == "model":
                from .conversation_model import UntrustedConversationDraft

                try:
                    checked_reply(
                        UntrustedConversationDraft(
                            text=reply["text"],
                            provider=reply["provider"],
                            model=reply["model"],
                            prompt_version=reply["prompt_version"],
                        ),
                        options,
                        service=service,
                        revision=revision,
                        runtime=verified.compiled_runtime,
                        locale=session.locale,
                        observations=observed,
                        expected_model=record["input"]["model_runtime"]["model"],
                    )
                except ValueError as exc:
                    raise EnrichmentIntegrityError("US-01 model provenance mismatch") from exc
            elif (
                reply["origin"] != "fallback"
                or reply["provider"] is not None
                or reply["model"] is not None
                or reply["text"] not in options
            ):
                raise EnrichmentIntegrityError("US-01 fallback provenance mismatch")
        current = repo.get_current_revision(sid, oid)
        return NaturalTurnRead(
            delivery_status="delivered" if reply else "pending",
            evidence=record["input"],
            input_hash=record["input_hash"],
            delivered_reply=reply,
            current_revision=current.model_dump(mode="json"),
            current_brief=current_brief(
                service, current, session.locale, verified.compiled_runtime
            ),
            is_current_revision=current.revision_id == revision.revision_id,
        )


def execute(service, sid, oid, request, model):
    """SO: source→bounded meaning→Matrix→atomic State→verified model→write-once delivery."""
    from jewelai_persistence import NotFoundError, StaleRevisionError
    from jewelai_persistence.models import MessageRow

    from .conversation_qwen import ConversationProviderError

    service = service._for_session(sid, oid)
    if not service._is_f04:
        raise ValueError("US-01 requires retained F artifacts")
    repo = service.repository
    try:
        existing = repo.get_initial_conversation_turn(sid, oid)
    except NotFoundError:
        existing = None
    if existing:
        if existing["input"]["request"] != request.model_dump(mode="json"):
            raise StaleRevisionError("First turn already exists with another input identity")
        retained = read(service, sid, oid)
        if retained.delivery_status == "pending":
            return deliver_pending(service, sid, oid, request, model, created=False)
        return retained, False
    repo.require_native_workflow(sid, oid)
    session = repo.get_design_session(sid, oid)
    if session.current_revision_id != request.expected_revision_id:
        raise StaleRevisionError("Current Product State changed")
    parent = repo.get_current_revision(sid, oid)
    verified = service._load_release()
    binding = bind_verified_release(
        service.artifact_store,
        verified.package_id,
        str(verified.artifact_version),
        active_release=service.active_release,
        validation_report=service.validation_report,
    )
    message_id, now = service._uuid(), service._clock()
    # Validate typed input eligibility before paying for either interpreter.
    # This checks explicit widget values only; raw text is not pre-interpreted.
    source_evidence(request, None, verified.compiled_runtime, session.locale)
    # Primary interpretation gets original user input/State, not Parser output.
    interpretation_context = _context(
        session,
        message_id,
        request,
        parent,
        None,
        binding,
        (),
        turn_binding={
            "session_id": str(sid),
            "organization_id": str(oid),
            "turn_id": str(request.turn_id),
        },
    )
    meaning_origin, failure = "model", None
    try:
        if model is None:
            raise ConversationProviderError("not_configured")
        meaning = SemanticProposal.model_validate(model.interpret(interpretation_context))
    except (ConversationProviderError, ValueError) as exc:
        meaning_origin, failure = "unavailable", getattr(exc, "code", "invalid_semantics")
        # No Parser-as-primary fallback: failed interpretation cannot authorize values.
        meaning = SemanticProposal(based_on_revision=parent.revision_id, intent="uncertain")
    parsed = (
        parse_full_message(
            request.original_text,
            locale=session.locale,
            dictionary=service.artifacts.dictionary,
            knowledge_runtime=verified.compiled_runtime,
        )
        if request.original_text.strip()
        else None
    )
    observed = source_evidence(request, parsed, verified.compiled_runtime, session.locale)
    decisions = arbitrate(
        meaning,
        text=request.original_text,
        parsed=parsed,
        revision=parent,
        dictionary=service.artifacts.dictionary,
        runtime=verified.compiled_runtime,
        locale=session.locale,
        selections=request.selections,
    )
    facts = decided_facts(meaning, decisions)
    conflict = any(d.outcome == "CLARIFY" for d in decisions)
    config = getattr(model, "config", None)
    model_runtime = {
        "provider": "qwen",
        "model": getattr(config, "model", None),
        "model_sha256": getattr(config, "model_sha256", None),
        "runtime_build": getattr(config, "runtime_build", None),
        "sampling": model.sampling_snapshot() if hasattr(model, "sampling_snapshot") else None,
    }
    source = MessageSource(message_id=str(message_id), recorded_at=now)
    design, matrix = matrix_transition(service, parent, source, facts, verified)
    decisions = matrix_arbitration(decisions, matrix)
    revision = (
        revise_design(
            parent,
            design,
            expected_revision_id=parent.revision_id,
            source=source,
            reason="US-01 Matrix-validated explicit first-turn requirements",
            created_at=now,
        )
        if design != parent.design
        else parent
    )
    payload = {
        "contract_version": CONTRACT,
        "session_id": str(sid),
        "organization_id": str(oid),
        "role_id": session.role_id,
        "locale": session.locale,
        "design_id": str(parent.design_id),
        "message_id": str(message_id),
        "message_sha256": _hash_text(request.original_text),
        "request": request.model_dump(mode="json"),
        "parsed": parsed.model_dump(mode="json") if parsed else None,
        "parent_hash": evidence_hash(parent),
        "result_revision_id": str(revision.revision_id),
        "result_hash": evidence_hash(revision),
        "knowledge_binding": binding.model_dump(mode="json"),
        "observations": [o.model_dump(mode="json") for o in observed],
        "eligible_facts": [f.model_dump(mode="json") for f in facts],
        "conflicted": conflict,
        "meaning": meaning.model_dump(mode="json"),
        "arbitration": [d.model_dump(mode="json") for d in decisions],
        "model_runtime": model_runtime,
        "meaning_origin": meaning_origin,
        "meaning_failure_code": failure,
        "matrix": matrix.model_dump(mode="json"),
    }

    def verify_input(reader):
        bound = copy(service)
        bound.repository = reader
        read(bound, sid, oid)

    created = repo.commit_initial_conversation_turn(
        sid=sid,
        oid=oid,
        expected_revision_id=parent.revision_id,
        revision=revision,
        message=MessageRow(
            message_id=message_id,
            session_id=sid,
            actor="user",
            content=request.original_text,
            created_at=now,
        ),
        payload=payload,
        verify=verify_input,
    )
    return deliver_pending(service, sid, oid, request, model, created=created is not False)


def deliver_pending(service, sid, oid, request, model, *, created):
    """Explicit same-turn POST may finish delivery, never interpretation/State again.

    GET never regenerates. Concurrent deliveries may each produce an untrusted
    draft; only the first write-once result is returned, never an unsaved loser.
    """
    from jewelai_domain.knowledge_runtime import KnowledgeReleaseBinding
    from jewelai_domain.models_v1_1 import validate_design_revision
    from jewelai_parser import read_full_message_parse_result
    from jewelai_persistence import StaleRevisionError

    from .conversation_qwen import ConversationProviderError

    repo = service.repository
    committed = read(service, sid, oid)
    if committed.delivery_status == "delivered":
        return committed, created
    if not committed.is_current_revision:
        raise StaleRevisionError("Cannot deliver a pending reply for superseded State")
    p = committed.evidence
    session = repo.get_design_session(sid, oid)
    revision = validate_design_revision(committed.current_revision)
    parsed = read_full_message_parse_result(p["parsed"]) if p["parsed"] is not None else None
    binding = KnowledgeReleaseBinding.model_validate(p["knowledge_binding"])
    observed = tuple(SemanticObservation.model_validate(o) for o in p["observations"])
    meaning = SemanticProposal.model_validate(p["meaning"])
    decisions = tuple(ArbitrationDecision.model_validate(d) for d in p["arbitration"])
    verified = service._load_release()
    message_id = UUID(p["message_id"])
    model_runtime = p["model_runtime"]
    brief = committed.current_brief
    options = reply_options(brief, observed, session.locale)
    context = _context(
        session,
        message_id,
        request,
        revision,
        parsed,
        binding,
        observed,
        turn_binding={
            "input_hash": committed.input_hash,
            "revision_id": str(revision.revision_id),
            "revision_hash": evidence_hash(revision),
        },
        options=options,
        meaning=meaning,
        decisions=decisions,
    )
    origin, failure, provider, model_id, text = "model", None, "qwen", None, None
    try:
        if model is None:
            raise ConversationProviderError("not_configured")
        draft = checked_reply(
            model.draft_reply(context),
            options,
            service=service,
            revision=revision,
            runtime=verified.compiled_runtime,
            locale=session.locale,
            observations=observed,
            expected_model=model_runtime["model"],
        )
        model_id, text = draft.model, draft.text
    except (ConversationProviderError, ValueError) as exc:
        origin, failure, provider, text = (
            "fallback",
            getattr(exc, "code", "invalid_reply"),
            None,
            options[0],
        )
    reply = {
        "contract_version": REPLY_VERSION,
        "origin": origin,
        "text": text,
        "provider": provider,
        "model": model_id,
        "prompt_version": REPLY_VERSION,
        "context_hash": evidence_hash(context.__dict__),
        "input_hash": committed.input_hash,
        "revision_id": str(revision.revision_id),
        "failure_code": failure,
    }

    def verify_delivery(reader):
        bound = copy(service)
        bound.repository = reader
        read(bound, sid, oid)

    try:
        repo.commit_initial_conversation_reply(
            sid=sid, oid=oid, input_hash=committed.input_hash, reply=reply, verify=verify_delivery
        )
    except StaleRevisionError:
        winner = read(service, sid, oid)
        if winner.delivery_status == "delivered":
            return winner, False
        raise
    return read(service, sid, oid), created
