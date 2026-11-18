"""Opt-in ST-01 creation binding and retained fallback reply, never a legacy parse.

This version is intentionally conservative: only an unambiguous first creation
request can bind the three approved targets through the pinned reviewed Library.
Parser evidence is immutable input, not rewritten to manufacture acceptance.
"""

import hashlib
import re
from datetime import datetime
from types import SimpleNamespace
from typing import Literal
from uuid import UUID

from jewelai_domain.clarification_state import Sha256, StrictEvidenceModel, evidence_hash
from jewelai_domain.knowledge_runtime import KnowledgeReleaseBinding
from jewelai_domain.models import Explicit, KnownValue

CONTRACT = "jewelai.st01.first-turn/1.0.0"
_CREATION = re.compile(
    r"^\s*(?:i\s+(?:want|would\s+like)(?:\s+to\s+(?:create|design|make))?\b|"
    r"(?:please\s+)?(?:create|design|make)\b|"
    r"(?:я\s+)?хочу(?:\s+(?:создать|сделать|спроектировать))?\b|"
    r"(?:пожалуйста[, ]+)?(?:создай(?:те)?|сделай(?:те)?|спроектируй(?:те)?)\b)",
    re.I,
)
_UNRESOLVED = re.compile(
    r"\?|\b(?:if|unless|maybe|perhaps|whether|compare|versus|than|or|если|возможно|может|"
    r"сравни\w*|чем|или|либо)\b",
    re.I,
)
# Syntax only: the count lexemes already recognized by the current Parser's
# quantity grammar. No numeric value, placement or repeated group is inferred.
_NOMINAL_COUNT = frozenset(
    {
        "two",
        "three",
        "four",
        "двумя",
        "два",
        "две",
        "тремя",
        "три",
        "четырьмя",
        "четыре",
    }
)
_STONE_QUALIFIER = re.compile(
    r"(?:center|centre|central|side|центральн(?:ый|ая|ое|ые|ого|ой|ому|ую|ым|ыми|ых|ом)|"
    r"боков(?:ой|ая|ое|ые|ого|ому|ую|ым|ыми|ых|ом))",
    re.I,
)
_TAIL_TOKEN = re.compile(r"made\s+(?:of|from)\b|[^\W_]+|[^\w\s]", re.I)
_TARGETS = ("jewelry_type", "metal.material", "metal.color")


class FirstTurnRequest(StrictEvidenceModel):
    schema_version: Literal["1.0.0"]
    message_id: UUID
    expected_revision_id: UUID


class CreationFact(StrictEvidenceModel):
    target: Literal["jewelry_type", "metal.material", "metal.color"]
    value: str
    candidate_id: str
    start: int
    end: int
    text: str
    mapping_ids: tuple[str, ...]


class FirstTurnEvidence(StrictEvidenceModel):
    contract_version: Literal["jewelai.st01.first-turn/1.0.0"] = CONTRACT
    organization_id: UUID
    session_id: UUID
    message_id: UUID
    message_sha256: Sha256
    parent_revision_id: UUID
    result_revision_id: UUID
    enrichment_cycle_id: UUID
    parser_version: Literal["1.3.0"]
    parse_sha256: Sha256
    knowledge_binding: KnowledgeReleaseBinding
    selection_eligible: bool
    facts: tuple[CreationFact, ...]


class FirstTurnReceipt(StrictEvidenceModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    binding: FirstTurnEvidence
    reply_origin: Literal["deterministic_fallback"] = "deterministic_fallback"
    reply_text: str
    created_at: datetime
    content_hash: Sha256


class FirstTurnRead(StrictEvidenceModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    receipt: FirstTurnReceipt
    is_current_revision: bool
    current_revision_id: UUID


def _creation_assertion_end(text, predicate):
    """Reuse native assertion boundaries; a connector alone is not a new predicate."""
    from jewelai_parser.full_message import (
        _REQUEST_START,
        _assertion_breaks,
        _sentence_bounds,
        _source_governance,
    )

    with _source_governance("1.3.0"):
        _, end = _sentence_bounds(text, predicate.start(), predicate.end())
        for left, right in _assertion_breaks(text):
            if predicate.end() <= left < end:
                following = text[right:end].lstrip()
                if _REQUEST_START.match(following):
                    return left
    return end


def _complete_nominal_tail(parsed, start, end):
    """Cover the whole relevant construction, not just its first preposition.

    Tagged Parser spans qualify nominal syntax only; only creation_facts can
    propose the three approved canonical bindings. Unknown words cannot be
    skipped, including an action after a valid material or gemstone phrase.
    """
    # A rejected nominal can qualify a negative adjunct syntactically; it never
    # enters creation_facts, whose positive-authority filter remains unchanged.
    spans = {}
    for candidate in parsed.candidates:
        span = candidate.evidence
        target = str(candidate.target or "")
        nominal = target in _TARGETS or target.startswith(("center_stone.", "side_stones."))
        adjective = target == "style" and candidate.subject == "overall_design"
        if (
            start <= span.start < span.end <= end
            and candidate.classification in {"requirement", "preference", "prohibition"}
            and (
                nominal
                and candidate.normalized_values
                and candidate.certainty == "explicit"
                or adjective
            )
        ):
            kind = "N" if target == "jewelry_type" or target.endswith(".material") else "A"
            previous = spans.get(span.start)
            if previous is None or span.end > previous[0]:
                spans[span.start] = (span.end, kind)
    text, index, tags = parsed.original_text, start, []
    while index < end:
        if text[index].isspace():
            index += 1
            continue
        if index in spans:
            index, kind = spans[index]
        else:
            token = _TAIL_TOKEN.match(text, index, end)
            if token is None:
                return False
            raw = " ".join(token.group().casefold().split())
            index = token.end()
            if raw in {
                "of",
                "in",
                "from",
                "with",
                "without",
                "из",
                "с",
                "со",
                "без",
                "made of",
                "made from",
            }:
                kind = "P"
            elif raw in {"create", "design", "make", "создать", "сделать", "спроектировать"}:
                # The same positive creation actions already allowed before the
                # noun may close a RU postposed creation request. An unknown
                # action is never admitted, nor can a valid one hide later text.
                if text[index:end].strip():
                    return False
                kind = "V"
            elif raw in {"not", "no", "не"}:
                kind = "X"
            elif raw in {"but", "но"}:
                kind = "B"
            elif raw in {"and", "и"}:
                kind = "J"
            elif raw == ",":
                kind = "K"
            elif raw in {"a", "an", "the"}:
                kind = "D"
            elif raw in _NOMINAL_COUNT or raw.isdecimal():
                kind = "Q"
            elif raw in {
                "stone",
                "stones",
                "gem",
                "gems",
                "камень",
                "камни",
                "камнями",
                "камней",
                "камнем",
            }:
                kind = "N"
            elif _STONE_QUALIFIER.fullmatch(raw):
                kind = "C"
            else:
                return False
        tags.append(kind)
    if not tags:
        return True
    nominal = r"D?Q?[ACN]*N"
    # Negated nominal adjuncts preserve the independent positive product request;
    # a bare negator cannot end the assertion and hide an informational action.
    phrase = "(?:PX?|XP?)" + nominal + "(?:JX?" + nominal + ")*"
    modifiers = "(?:(?:K?B?|J)?" + phrase + ")+"
    return bool(re.fullmatch("(?:" + modifiers + ")?V?", "".join(tags)))


def _direct_creation_subject(parsed, product, predicate):
    """Prove the selected noun is the request's direct object, not its topic.

    A desire verb alone grants no authority. Between it and the product head,
    permit only articles/pair-of and source-backed adjectival candidates already
    recognized by the current Parser. Uncovered heads/complements (information,
    advice, guide, to know, etc.) therefore fail without a synonym blacklist.
    Recognized aesthetic modifiers qualify syntax only; they remain unaccepted.
    """
    end = _creation_assertion_end(parsed.original_text, predicate)
    if product is None or not predicate.end() <= product.start < product.end <= end:
        return False
    start = predicate.end()
    prefix = list(parsed.original_text[start : product.start])
    for candidate in parsed.candidates:
        span = candidate.evidence
        modifier = (
            (
                candidate.target in {"metal.material", "metal.color"}
                and candidate.subject == "product_body"
                and candidate.certainty == "explicit"
            )
            or candidate.target == "style"
            and candidate.subject == "overall_design"
        )
        if (
            modifier
            and candidate.classification in {"requirement", "preference"}
            and start <= span.start < span.end <= product.start
        ):
            prefix[span.start - start : span.end - start] = " " * (span.end - span.start)
    remaining = " ".join("".join(prefix).split())
    if not re.fullmatch(r"(?:(?:a|an|the|some)(?:\s+|$))?(?:pair\s+of)?", remaining, re.I):
        return False
    return _complete_nominal_tail(parsed, product.end, end)


def creation_facts(parsed, runtime):
    """Recompute from source spans and compiled mappings, not Policy.effect prose."""
    predicate = _CREATION.match(parsed.original_text)
    if predicate is None or _UNRESOLVED.search(parsed.original_text):
        return False, ()
    from jewelai_parser.knowledge_matcher import KnowledgeLibraryMatcher

    matcher = KnowledgeLibraryMatcher(runtime)
    facts = []
    for target in _TARGETS:
        matches = []
        for c in parsed.candidates:
            if (
                str(c.target) != target
                or c.subject not in {"product", "product_body"}
                or c.certainty != "explicit"
                or c.classification not in {"requirement", "preference"}
                or len(c.normalized_values) != 1
            ):
                continue
            value = c.normalized_values[0]
            match = matcher.match(
                c.evidence.text, locale=parsed.requested_locale, allowed_concept_ids=(value,)
            )
            mappings = (
                (match.candidate.mapping_id,)
                if match.outcome == "resolved" and match.candidate.mapping_mode == "DIRECT"
                else ()
            )
            if mappings:
                matches.append(
                    CreationFact(
                        target=target,
                        value=value,
                        candidate_id=c.candidate_id,
                        start=c.evidence.start,
                        end=c.evidence.end,
                        text=c.evidence.text,
                        mapping_ids=mappings,
                    )
                )
        # Multiple alternative values never become an arbitrary first choice.
        if matches and len({m.value for m in matches}) == 1:
            facts.append(matches[0])
    # A parser target hint is not sufficient component ownership. Admit only a
    # direct product-material construction; e.g. "gold earrings" / "серьги из
    # белого золота". "earrings with gold center stones" is not product metal.
    by_target = {f.target: f for f in facts}
    product = by_target.get("jewelry_type")
    if not _direct_creation_subject(parsed, product, predicate):
        return False, ()
    material = by_target.get("metal.material")
    color = by_target.get("metal.color")
    body_owned = False
    if product is not None and material is not None:
        text = parsed.original_text
        if material.end <= product.start:
            body_owned = not text[material.end : product.start].strip()
        elif product.end <= material.start:
            material_start = material.start
            if (
                color is not None
                and color.end <= material.start
                and not text[color.end : material.start].strip()
            ):
                material_start = color.start
            body_owned = bool(
                re.fullmatch(
                    r"\s+(?:из|of|in|made\s+(?:of|from))\s+",
                    text[product.end : material_start],
                    re.I,
                )
            )
    color_owned = (
        body_owned
        and color is not None
        and color.end <= material.start
        and not parsed.original_text[color.end : material.start].strip()
    )
    return True, tuple(
        f
        for f in facts
        if f.target == "jewelry_type"
        or f.target == "metal.material"
        and body_owned
        or f.target == "metal.color"
        and color_owned
    )


def creation_design(revision, facts, source):
    payload = revision.design.model_dump(mode="json")
    for fact in facts:
        keys = fact.target.split(".")
        current = revision.design
        dest = payload
        for key in keys[:-1]:
            current = getattr(current, key)
            dest = dest[key]
        old = getattr(current, keys[-1])
        if isinstance(old, KnownValue) and old.value == fact.value:
            continue  # Compatible reaffirmation retains the original authority.
        if old is not None and (old.locked or old.confirmed or old.availability != "unknown"):
            raise ValueError("First creation cannot replace existing accepted authority")
        dest[keys[-1]] = Explicit[str](value=fact.value, source=source).model_dump(mode="json")
    return type(revision.design).model_validate(payload)


def make_receipt(*, revision, authoritative, parsed, binding, source, request, cycle_id, now):
    eligible, facts = creation_facts(parsed, binding.compiled_runtime)
    evidence = FirstTurnEvidence(
        organization_id=request.organization_id,
        session_id=request.session_id,
        message_id=request.message_id,
        message_sha256=hashlib.sha256(parsed.original_text.encode()).hexdigest(),
        parent_revision_id=revision.revision_id,
        result_revision_id=authoritative.revision_id,
        enrichment_cycle_id=cycle_id,
        parser_version=parsed.parse_version,
        parse_sha256=evidence_hash(parsed),
        knowledge_binding=source,
        selection_eligible=eligible,
        facts=facts,
    )
    ru = parsed.requested_locale == "ru"
    labels = {"jewelry_type": "тип", "metal.material": "металл", "metal.color": "цвет металла"}
    terms = {m.mapping_id: m.canonical_term for m in binding.compiled_runtime.language_mappings}
    accepted = "; ".join(
        f"{labels[f.target] if ru else f.target}: {terms[f.mapping_ids[0]]}" for f in facts
    )
    # Honest bounded presentation of accepted facts only. No model is selected.
    text = (
        "Запрос сохранён. Резервный ответ без языковой модели. "
        if ru
        else "Your request is saved. Fallback reply without a language model. "
    )
    text += (
        ("Принято: " if ru else "Accepted: ") + accepted + ". "
        if facts
        else ("Новые параметры не приняты. " if ru else "No new parameters were accepted. ")
    )
    text += (
        "Остальная часть исходного запроса сохранена, но не принята как параметры дизайна."
        if ru
        else "The rest of the original request is retained but not accepted as design parameters."
    )
    payload = dict(
        binding=evidence.model_dump(mode="json"),
        reply_text=text,
        reply_origin="deterministic_fallback",
        created_at=now,
        schema_version="1.0.0",
    )
    receipt = FirstTurnReceipt(**payload, content_hash="0" * 64)
    return receipt.model_copy(
        update={
            "content_hash": evidence_hash(receipt.model_dump(mode="json", exclude={"content_hash"}))
        }
    )


def validate_receipt(payload):
    receipt = FirstTurnReceipt.model_validate(payload)
    if (
        evidence_hash(receipt.model_dump(mode="json", exclude={"content_hash"}))
        != receipt.content_hash
    ):
        raise ValueError("First-turn receipt hash mismatch")
    return receipt


def verify_source(service, repo, sid, oid, plan, cycle, message, verified):
    """New explicit source dispatch; legacy verifier is never invoked or weakened."""
    from jewelai_parser.full_message import _parse_recorded_message

    from .f04_planning import f04_evaluation, input_context
    from .prompt_enrichment_runtime_v2 import source_message

    payload = repo.get_first_conversation_turn(sid, oid)
    receipt = validate_receipt(payload)
    ev = receipt.binding
    parent = repo.get_revision(sid, cycle.result.context.source_revision_id, oid)
    result = repo.get_revision(sid, cycle.specification_revision_id, oid)
    _, source = source_message(service, sid, message.message_id, oid, repository=repo)
    parsed = _parse_recorded_message(
        message.content,
        parse_version=ev.parser_version,
        locale=plan.locale.value,
        dictionary=service.artifacts.dictionary,
        knowledge_runtime=verified.compiled_runtime,
    )
    eligible, facts = creation_facts(parsed, verified.compiled_runtime)
    pin = repo.get_knowledge_release_pin(sid, oid)
    if (
        (
            ev.organization_id,
            ev.session_id,
            ev.message_id,
            ev.parent_revision_id,
            ev.result_revision_id,
            ev.enrichment_cycle_id,
        )
        != (
            oid,
            sid,
            message.message_id,
            parent.revision_id,
            result.revision_id,
            cycle.enrichment_cycle_id,
        )
        or ev.message_sha256 != hashlib.sha256(message.content.encode()).hexdigest()
        or ev.parse_sha256 != evidence_hash(parsed)
        or ev.knowledge_binding != pin.binding
        or ev.knowledge_binding.release_identity
        != (
            verified.package_id,
            str(verified.artifact_version),
            verified.runtime_sha256,
            verified.validation_report_sha256,
        )
        or ev.selection_eligible != eligible
        or ev.facts != facts
    ):
        raise ValueError("ST-01 source/binding mismatch")
    proposed = creation_design(parent, facts, source)
    if result.design != proposed or (
        (result.revision_id == parent.revision_id) != (proposed == parent.design)
    ):
        raise ValueError("ST-01 accepted transition mismatch")
    if result != parent and (
        result.parent_revision_id != parent.revision_id or result.event.source != source
    ):
        raise ValueError("ST-01 transition ancestry/source mismatch")
    context = input_context(
        plan.scope, parent, cycle.enrichment_cycle_id, 1, service.artifacts, verified
    )
    if context != cycle.result.context:
        raise ValueError("ST-01 enrichment context mismatch")
    evaluated = f04_evaluation(
        service._evaluate(result, parsed, source), revision=result, context=context
    )
    if evaluated.enrichment_result != cycle.result:
        raise ValueError("ST-01 Matrix evaluation mismatch")
    expected = make_receipt(
        revision=parent,
        authoritative=result,
        parsed=parsed,
        binding=verified,
        source=ev.knowledge_binding,
        request=SimpleNamespace(organization_id=oid, session_id=sid, message_id=message.message_id),
        cycle_id=cycle.enrichment_cycle_id,
        now=cycle.created_at,
    )
    if receipt != expected:
        raise ValueError("ST-01 retained reply/evidence mismatch")
    return evaluated


def start(service, sid, oid, request):
    from .prompt_enrichment_runtime import InitialEnrichmentRequestV2
    from .prompt_enrichment_runtime_v2 import start_initial_message

    service._require_native_workflow(sid, oid)
    bound = service._for_session(sid, oid)
    if not bound._is_f04:
        raise ValueError("ST-01 requires the retained F profile")
    command = InitialEnrichmentRequestV2(
        schema_version="2.0.0",
        session_id=sid,
        organization_id=oid,
        message_id=request.message_id,
        expected_revision_id=request.expected_revision_id,
    )
    # The old initial route remains unchanged. This opts in to the new contract.
    return start_initial_message(bound, command, first_turn=True)


def read(service, sid, oid):
    from .prompt_enrichment_runtime_v2 import boundary

    @boundary
    def verified_read():
        with service.repository.read_enrichment_history(sid, oid) as repo:
            payload = repo.get_first_conversation_turn(sid, oid)
            receipt = validate_receipt(payload)
            # Full source/Matrix/revision verification, not hash-only metadata.
            bound = service._for_session(sid, oid, repository=repo)
            bound.get_current_state(sid, oid)
            current = repo.get_current_revision(sid, oid)
            return FirstTurnRead(
                receipt=receipt,
                current_revision_id=current.revision_id,
                is_current_revision=current.revision_id == receipt.binding.result_revision_id,
            )

    return verified_read()
