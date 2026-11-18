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
    r"^\s*(?:i\s+(?:want|would\s+like)\b|(?:please\s+)?(?:create|design|make)\b|"
    r"(?:я\s+)?хочу\b|(?:пожалуйста[, ]+)?(?:создай(?:те)?|сделай(?:те)?|спроектируй(?:те)?)\b)",
    re.I,
)
_UNRESOLVED = re.compile(
    r"\?|\b(?:if|unless|maybe|perhaps|whether|compare|versus|than|or|если|возможно|может|"
    r"сравни\w*|чем|или|либо)\b|want\s+(?:to\s+know|information)|хочу\s+(?:узнать|спросить)",
    re.I,
)
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


def creation_facts(parsed, runtime):
    """Recompute from source spans and compiled mappings, not Policy.effect prose."""
    eligible = bool(_CREATION.search(parsed.original_text)) and not _UNRESOLVED.search(
        parsed.original_text
    )
    if not eligible:
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
