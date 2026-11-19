"""Independent source/Parser/SO controls, including a missing Parser candidate."""

from copy import deepcopy
from dataclasses import replace

import pytest
from jewelai_parser import parse_full_message
from test_conversation_model import context_inputs as context_inputs
from test_natural_turn import Model
from test_professional_knowledge_http import real_config as real_config

from jewelai_api.conversation_model import build_conversation_context
from jewelai_api.semantic_proposal import SemanticProposal, arbitrate


def inputs(context_inputs, text, locale="en"):
    # A fresh canonical State, with immutable fixture revision/authority retained.
    old = context_inputs["committed_revision"]
    data = old.design.model_dump(mode="json")
    data["jewelry_type"] = None
    data["metal"]["material"] = None
    data["metal"]["color"] = None
    revision = old.model_copy(update={"design": type(old.design).model_validate(data)})
    args = {**context_inputs, "committed_revision": revision}
    context = build_conversation_context(**args, original_text=text, locale=locale)
    context = replace(context, semantic_evidence_json='{"typed_selections":[]}')
    proposal = Model().interpret(context)
    parsed = parse_full_message(
        text,
        locale=locale,
        dictionary=args["dictionary"],
        knowledge_runtime=args["active_runtime"].compiled_runtime,
    )
    return proposal, dict(
        text=text,
        parsed=parsed,
        revision=revision,
        dictionary=args["dictionary"],
        runtime=args["active_runtime"].compiled_runtime,
        locale=locale,
    )


@pytest.mark.parametrize(
    "locale,text",
    [
        ("en", "I want white gold earrings with two sapphires."),
        ("ru", "Хочу серьги из белого золота с двумя сапфирами."),
    ],
)
def test_explicit_product_accepts_but_stone_allocation_is_not_invented(
    context_inputs, locale, text
):
    proposal, args = inputs(context_inputs, text, locale)
    before = args["revision"].model_dump_json()
    decisions = arbitrate(proposal, **args)
    outcomes = {c.target: d.outcome for c, d in zip(proposal.changes, decisions, strict=True)}
    assert outcomes == {
        "jewelry_type": "ACCEPT",
        "metal.material": "ACCEPT",
        "metal.color": "ACCEPT",
        "stone.material": "CLARIFY",
        "stone.count": "CLARIFY",
    }
    assert args["revision"].model_dump_json() == before


def test_missing_parser_candidate_is_not_an_automatic_veto(context_inputs):
    proposal, args = inputs(context_inputs, "I want white gold earrings.")
    parsed = args["parsed"]
    args["parsed"] = parsed.model_copy(
        update={"candidates": tuple(c for c in parsed.candidates if c.target != "jewelry_type")}
    )
    decisions = arbitrate(proposal, **args)
    d = next(
        d for c, d in zip(proposal.changes, decisions, strict=True) if c.target == "jewelry_type"
    )
    assert d.outcome == "ACCEPT" and d.mapping_ids and not d.parser_candidate_ids


def test_compact_quotes_are_anchored_by_so_and_original_proposal_is_unchanged(context_inputs):
    proposal, args = inputs(context_inputs, "I want white gold earrings with two sapphires.")
    raw = proposal.model_dump(mode="json")
    for c in raw["changes"]:
        c["source_phrase"] = c["source"]["text"]
        c["source"] = None
    quoted = SemanticProposal.model_validate(raw)
    before = quoted.model_dump_json()
    decisions = arbitrate(quoted, **args)
    assert [d.outcome for d in decisions] == ["ACCEPT", "ACCEPT", "ACCEPT", "CLARIFY", "CLARIFY"]
    for decision in decisions:
        span = decision.source_span
        assert span is not None and args["text"][span.start : span.end] == span.text
    assert quoted.model_dump_json() == before


@pytest.mark.parametrize("phrase", ["platinum", "gold"])
def test_missing_or_repeated_quote_cannot_select_arbitrary_occurrence(context_inputs, phrase):
    proposal, args = inputs(
        context_inputs, "I want white gold earrings and I do not want gold earrings."
    )
    c = proposal.changes[1].model_copy(update={"source": None, "source_phrase": phrase})
    proposal = proposal.model_copy(update={"changes": (c,)})
    result = arbitrate(proposal, **args)[0]
    assert result.outcome == "CLARIFY" and result.reason == "source_mismatch"
    assert result.source_span is None


@pytest.mark.parametrize(
    "text",
    [
        "I want information about white gold earrings.",
        "I want to discuss white gold earrings.",
        "Хочу серьги из белого золота обсудить.",
        "I do not want white gold earrings.",
        "I want earrings with gold center stones.",
    ],
)
def test_interpreter_agreement_never_overrides_source_intent_or_owner(context_inputs, text):
    proposal, args = inputs(context_inputs, text, "ru" if "Х" in text else "en")
    decisions = arbitrate(proposal, **args)
    if "gold center stones" in text:
        assert (
            next(
                d
                for c, d in zip(proposal.changes, decisions, strict=True)
                if c.target == "metal.material"
            ).outcome
            != "ACCEPT"
        )
    else:
        assert not any(d.outcome == "ACCEPT" for d in decisions)


@pytest.mark.parametrize(
    "kind",
    ["bad_span", "wrong_owner", "wrong_value", "wrong_revision", "question", "recommendation"],
)
def test_malformed_or_nonselection_proposals_never_write(context_inputs, kind):
    proposal, args = inputs(context_inputs, "I want white gold earrings.")
    payload = deepcopy(proposal.model_dump(mode="json"))
    c = payload["changes"][0]
    if kind == "bad_span":
        c["source"]["text"] = "ring"
    elif kind == "wrong_owner":
        c["component"] = "center_stone"
    elif kind == "wrong_value":
        c["value"] = "ring"
    elif kind == "wrong_revision":
        payload["based_on_revision"] = "00000000-0000-0000-0000-000000000000"
    else:
        c["disposition"] = kind
    changed = SemanticProposal.model_validate(payload)
    assert arbitrate(changed, **args)[0].outcome != "ACCEPT"


def test_same_metal_at_different_sources_cannot_borrow_product_ownership(context_inputs):
    text = "I want gold earrings with gold center stones."
    proposal, args = inputs(context_inputs, text)
    material = next(c for c in proposal.changes if c.target == "metal.material")
    alien = material.model_copy(
        update={
            "proposal_id": "alien_gold",
            "source": material.source.model_copy(
                update={
                    "start": text.rindex("gold"),
                    "end": text.rindex("gold") + 4,
                }
            ),
        }
    )
    proposal = proposal.model_copy(update={"changes": (*proposal.changes, alien)})
    decisions = {d.proposal_id: d for d in arbitrate(proposal, **args)}
    assert decisions[material.proposal_id].outcome == "ACCEPT"
    assert decisions[alien.proposal_id].outcome != "ACCEPT"
