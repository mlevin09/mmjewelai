"""F01 real persisted HTTP evidence using the existing controlled runtime fixture."""

import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from jewelai_domain.dictionary import DictionaryLocale
from test_core_intent import (
    CHECKED_FIELDS,
    _current,
    _field,
    _immutable_history,
    _scenario,
    _submit,
    exercise_core_lifecycle,
)
from test_prompt_enrichment_composition import _client

F01_CASES = (
    (
        "F01-01",
        "A yellow gold ring with an oval diamond center stone.",
        "en",
        {
            "metal.material": "gold",
            "metal.color": "yellow",
            "center_stone.material": "diamond",
            "center_stone.shape": "oval",
        },
    ),
    (
        "F01-02",
        "Кольцо из золота с овальным алмазом.",
        "ru",
        {
            "metal.material": "gold",
            "center_stone.material": "diamond",
            "center_stone.shape": "oval",
        },
    ),
    (
        "F01-03",
        "Gold ring. Центральный овальный алмаз. Без боковых камней.",
        "ru",
        {
            "metal.material": "gold",
            "center_stone.material": "diamond",
            "center_stone.shape": "oval",
        },
    ),
    (
        "F01-04",
        "A gold ring with an oval diamond center stone and round sapphire side stones.",
        "en",
        {
            "metal.material": "gold",
            "center_stone.material": "diamond",
            "center_stone.shape": "oval",
        },
    ),
    ("F01-05", "Platinum shank with rose-gold prongs.", "en", {}),
    (
        "F01-06",
        "A matte platinum split-shank ring with an east-west blue sapphire.",
        "en",
        {"metal.material": "platinum"},
    ),
    (
        "F01-07",
        "Gold or platinum ring with an oval diamond.",
        "en",
        {"center_stone.material": "diamond", "center_stone.shape": "oval"},
    ),
    (
        "F01-08",
        "Gold and platinum ring with an oval diamond.",
        "en",
        {"center_stone.material": "diamond", "center_stone.shape": "oval"},
    ),
    (
        "F01-09",
        "Maybe platinum. An oval diamond ring.",
        "en",
        {"center_stone.material": "diamond", "center_stone.shape": "oval"},
    ),
    (
        "F01-10",
        "I want a gold ring and I do not want a platinum ring.",
        "en",
        {"metal.material": "gold"},
    ),
    (
        "F01-11",
        "An oval diamond ring. No side stones.",
        "en",
        {"center_stone.material": "diamond", "center_stone.shape": "oval"},
    ),
    ("F01-12", "A gold ring. No prongs.", "en", {"metal.material": "gold"}),
    (
        "F01-13",
        "No side stones. An oval diamond center stone.",
        "en",
        {"center_stone.material": "diamond", "center_stone.shape": "oval"},
    ),
    ("control-body", "A platinum ring with gold prongs.", "en", {"metal.material": "platinum"}),
    ("control-head", "A gold ring with a platinum head.", "en", {"metal.material": "gold"}),
    (
        "control-side",
        "Oval emerald side stones with a diamond center stone.",
        "en",
        {"center_stone.material": "diamond"},
    ),
)


F01_CASES += (
    (
        "control-component-material-list",
        "A gold ring with platinum and rose-gold prongs.",
        "en",
        {"metal.material": "gold"},
    ),
    (
        "control-component-color-list",
        "A platinum ring with white and yellow gold prongs.",
        "en",
        {"metal.material": "platinum"},
    ),
    (
        "control-component-material-list-ru",
        "Кольцо из золота с платиной и розовым золотом в крапанах.",
        "ru",
        {"metal.material": "gold"},
    ),
    (
        "control-component-color-list-mixed",
        "Gold ring с белым и жёлтым золотом в крапанах.",
        "ru",
        {"metal.material": "gold"},
    ),
    ("control-coating", "A platinum ring with gold coating.", "en", {"metal.material": "platinum"}),
    (
        "control-components",
        "A white gold ring with platinum shank and rose-gold prongs.",
        "en",
        {"metal.material": "gold", "metal.color": "white"},
    ),
    (
        "control-same-material",
        "An oval diamond center stone and emerald side stones. A gold ring.",
        "en",
        {
            "metal.material": "gold",
            "center_stone.material": "diamond",
            "center_stone.shape": "oval",
        },
    ),
    (
        "control-reordered-ru",
        "Овальные изумруды по бокам. Алмаз в центре. Кольцо из золота.",
        "ru",
        {"metal.material": "gold", "center_stone.material": "diamond"},
    ),
    (
        "control-mixed-component",
        "Gold ring с платиновой шинкой и розовым золотом в крапанах.",
        "ru",
        {"metal.material": "gold"},
    ),
    (
        "control-style-cut",
        "A white gold pendant with an emerald center stone in a step cut and a minimalist style.",
        "en",
        {
            "metal.material": "gold",
            "metal.color": "white",
            "center_stone.material": "emerald",
            "center_stone.cut": "step_cut",
            "style": ["minimalist"],
        },
    ),
    (
        "control-uncertain-component",
        "Maybe a platinum shank. An oval diamond ring.",
        "en",
        {"center_stone.material": "diamond", "center_stone.shape": "oval"},
    ),
)


def exercise_f01_case(engine, tmp_path, monkeypatch, case, binding):
    case_id, text, locale, expected = case
    with _scenario(engine, tmp_path, monkeypatch, binding=binding, locale=locale) as ctx:
        before, actual, state, message = _submit(ctx, text)
        parsed = ctx.evaluations[0][1]
        evaluation = ctx.evaluations[0][2]
        facts = {f.target: f for f in state.final_output.internal_final_prompt.design_facts}
        for target in set(CHECKED_FIELDS) | set(expected):
            field = _field(actual, target)
            if target in expected:
                value = list(field.value) if isinstance(field.value, tuple) else field.value
                assert value == expected[target], (target, field)
                assert field.source.message_id == message["message_id"]
                assert facts[target].value == expected[target]
                values = (
                    expected[target] if isinstance(expected[target], list) else [expected[target]]
                )
                for value in values:
                    label = ctx.runtime.artifacts.dictionary[value].canonical_terms.for_locale(
                        DictionaryLocale(locale)
                    )
                    assert label in state.final_output.description.text
                assert message["message_id"] in facts[target].source_ids
            else:
                assert field is None and target not in facts, (target, field)
        assert actual.design.side_stones == () and actual.design.metal.components is None
        assert actual.design.metal.finish is None and actual.design.metal.purity is None
        assert (
            actual.design.center_stone.color is None
            and actual.design.center_stone.orientation is None
        )
        assert actual.design.construction.shank_configuration is None
        # Every deferred source-backed relationship is preserved as unresolved,
        # never represented as an accepted component/global fact.
        evidence = state.clarification_plan.constraint_evidence
        for disposition in evaluation.dispositions:
            c = disposition.candidate
            if (
                c.classification == "requirement"
                and disposition.outcome == "DEFERRED"
                and (c.normalized_values or c.subject != "unknown")
            ):
                entries = [e for e in evidence if e.source_candidate_id == c.candidate_id]
                if not entries:
                    if c.certainty == "ambiguous":
                        assert any(
                            c.candidate_id in q.source_candidate_ids
                            for q in state.clarification_plan.questions
                        ) or any(
                            e.candidate_id == c.candidate_id
                            for e in state.clarification_plan.unasked_evidence
                        )
                        continue
                    # The same term/owner already accepted through Dictionary or
                    # an approved semantic binding must not be labelled unapplied.
                    assert any(
                        d.outcome in {"APPLIED", "KEPT", "NO_CHANGE"}
                        and d.candidate.evidence == c.evidence
                        for d in evaluation.dispositions
                    )
                    continue
                entry = entries[0]
                assert entry.status == "unresolved" and entry.canonical_target is None
                assert (
                    entry.source_span_start
                    <= c.evidence.start
                    < c.evidence.end
                    <= entry.source_span_end
                )
                assert c.evidence.text in entry.original_wording
                assert entry.source.message_id == message["message_id"]
                assert (
                    text[entry.source_span_start : entry.source_span_end] == entry.original_wording
                )
                assert entry in state.final_output.internal_final_prompt.constraint_evidence
                assert entry.original_wording in state.final_output.description.text
        if case_id in {"F01-04", "control-same-material"}:
            for c in parsed.candidates:
                if c.evidence.text.casefold() in {"round", "sapphire", "emerald"}:
                    assert c.subject == "side_stones" and c.parser_update is None
        if case_id == "F01-05":
            assert actual.design.center_stone.setting is None
            assert all(c.parser_update is None for c in parsed.candidates)
        if "ring" in text.casefold() or "Кольцо" in text:
            assert actual.design.jewelry_type.value == "ring"
            assert facts["jewelry_type"].value == "ring"
        history = _immutable_history(ctx)
        pin = ctx.repo.get_knowledge_release_pin(ctx.sid, ctx.org)
        output = state.final_output.model_dump(mode="json")
        print(
            "F01_TRACE "
            + json.dumps(
                {
                    "case": case_id,
                    "backend": engine.dialect.name,
                    "p010": binding,
                    "message_id": message["message_id"],
                    "locale": locale,
                    "expected": expected,
                    "actual": {k: f.value for k, f in facts.items()},
                    "unapplied": [
                        e.model_dump(mode="json") for e in evidence if e.status == "unresolved"
                    ],
                    "description": state.final_output.description.text,
                    "ifp_hash": state.final_output.internal_final_prompt.content_hash,
                },
                ensure_ascii=False,
            )
        )
    restarted, app, provider = _client(engine, ctx.config)
    with restarted:
        r = restarted.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output", headers=ctx.headers
        )
        assert r.status_code == 200 and r.json() == output
        restored = app.state.prompt_enrichment_service
        assert (
            _immutable_history(SimpleNamespace(repo=restored.repository, sid=ctx.sid, org=ctx.org))
            == history
        )
        assert restored.repository.get_current_revision(ctx.sid, ctx.org) == actual
        assert restored.repository.get_knowledge_release_pin(ctx.sid, ctx.org) == pin
        assert (
            restored.repository.get_message(ctx.sid, UUID(message["message_id"]), ctx.org).content
            == text
        )
        assert provider.calls == []


@pytest.mark.parametrize("binding", (False, True))
@pytest.mark.parametrize("case", F01_CASES, ids=[c[0] for c in F01_CASES])
def test_f01_http(engine, tmp_path, monkeypatch, binding, case):
    exercise_f01_case(engine, tmp_path, monkeypatch, case, binding)


@pytest.mark.parametrize("binding", (False, True))
def test_f01_lifecycle(engine, tmp_path, monkeypatch, binding):
    exercise_core_lifecycle(engine, tmp_path, monkeypatch, binding, coordinated=True)


@pytest.mark.parametrize("groups", (0, 1, 2))
def test_existing_ids_are_never_invented_or_rebound(engine, tmp_path, monkeypatch, groups):
    from conftest import NOW
    from jewelai_domain.models import MessageSource
    from jewelai_domain.revisions import revise_design
    from test_prompt_enrichment_http import _message

    with _scenario(engine, tmp_path, monkeypatch) as ctx:
        current = _current(ctx)
        message = _message(
            ctx.client,
            str(ctx.sid),
            str(ctx.org),
            "Explicit TEST-ONLY pre-existing object identities",
        )
        source = MessageSource(message_id=message["message_id"], recorded_at=NOW)
        payload = current.design.model_dump(mode="json")
        payload["side_stones"] = [
            {"group_id": f"existing_{i}", "stones": {}} for i in range(groups)
        ]
        payload["metal"]["components"] = {
            "availability": "value",
            "origin": "explicit",
            "value": [{"component_id": "existing_prong"}],
            "confirmed": False,
            "locked": False,
            "source": source.model_dump(mode="json"),
        }
        seeded = revise_design(
            current,
            payload,
            expected_revision_id=current.revision_id,
            source=source,
            reason="Existing fixture objects",
            created_at=NOW,
        )
        ctx.repo.append_revision_cas(ctx.sid, ctx.org, current.revision_id, seeded)
        _, actual, state, _ = _submit(ctx, "Two side stones with an emerald and a platinum shank.")
        assert actual.design.metal.components == seeded.design.metal.components
        assert actual.design.metal.material is None
        assert tuple(g.group_id for g in actual.design.side_stones) == tuple(
            g.group_id for g in seeded.design.side_stones
        )
        assert all(
            g.stones == seeded.design.side_stones[i].stones
            for i, g in enumerate(actual.design.side_stones)
        )
        if groups == 1:
            assert actual.design.side_stones[0].quantity.value.value == 2
        else:
            assert all(g.quantity is None for g in actual.design.side_stones)
        assert state.final_output.internal_final_prompt.schema_version == "2.1.0"


def test_f01_locked_body_not_replaced_by_component_or_global_request(engine, tmp_path, monkeypatch):
    from conftest import NOW
    from jewelai_domain.revisions import lock_field
    from test_core_intent import _seed

    with _scenario(engine, tmp_path, monkeypatch) as ctx:
        original = _seed(ctx, material=True)
        locked = lock_field(
            original,
            "metal.material",
            expected_revision_id=original.revision_id,
            source=original.design.metal.material.source,
            reason="Fixture LOCK",
            created_at=NOW,
        )
        ctx.repo.append_revision_cas(ctx.sid, ctx.org, original.revision_id, locked)
        _, actual, state, _ = _submit(ctx, "A platinum ring with gold prongs.")
        assert actual.design.metal.material == locked.design.metal.material
        assert any(
            "LOCKED_FIELD_CONFLICT" in d.parser_issue_codes
            for d in ctx.evaluations[0][2].dispositions
        )
        fact = next(
            f
            for f in state.final_output.internal_final_prompt.design_facts
            if f.target == "metal.material"
        )
        assert fact.value == "gold" and fact.locked


def test_f01_three_cycle_keep_and_component_delta(engine, tmp_path, monkeypatch):
    with _scenario(engine, tmp_path, monkeypatch, binding=True) as ctx:
        _, first, initial, _ = _submit(
            ctx, "An asymmetric ring — do not make it symmetrical. Gold body."
        )
        keep = next(
            e
            for e in initial.clarification_plan.constraint_evidence
            if e.status == "active"
            and e.kind == "preservation"
            and e.semantic_subject == "composition.symmetry_mode"
        )
        original = _immutable_history(ctx)
        _, _, _, _ = _submit(
            ctx, "A gold ring with a platinum shank and oval diamond center stone.", "corrections"
        )
        _, actual, state, _ = _submit(
            ctx, "No side stones and I want an oval emerald center stone.", "corrections"
        )
        assert state.enrichment_cycle_number == 3
        assert actual.design.metal.material == first.design.metal.material
        assert actual.design.composition == first.design.composition
        assert actual.design.center_stone.material.value == "emerald"
        assert (
            next(
                e
                for e in state.clarification_plan.constraint_evidence
                if e.evidence_id == keep.evidence_id
            )
            == keep
        )
        assert keep in state.final_output.internal_final_prompt.constraint_evidence
        history = _immutable_history(ctx)
        assert all(history[k].get(i) == v for k, rows in original.items() for i, v in rows.items())
        output = state.final_output.model_dump(mode="json")
    restarted, app, provider = _client(engine, ctx.config)
    with restarted:
        r = restarted.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output", headers=ctx.headers
        )
        assert r.status_code == 200 and r.json() == output
        assert (
            _immutable_history(
                SimpleNamespace(
                    repo=app.state.prompt_enrichment_service.repository, sid=ctx.sid, org=ctx.org
                )
            )
            == history
        )
        assert provider.calls == []


@pytest.mark.parametrize(
    "subject,target,value",
    (
        ("band", "metal.material", {"kind": "term", "text": "gold"}),
        ("prongs", "metal.color", {"kind": "term", "text": "white"}),
        ("unknown", "metal.material", {"kind": "term", "text": "platinum"}),
        ("prongs", "style", {"kind": "style_terms", "terms": ["minimalist"]}),
    ),
)
def test_matrix_rejects_forged_global_component_update(subject, target, value):
    from conftest import ROOT
    from jewelai_domain import load_domain_dictionary
    from jewelai_parser import StructuredCandidate

    from jewelai_api.parsed_enrichment import _prepare_candidate

    candidate = StructuredCandidate(
        candidate_id="forged",
        target=target,
        subject=subject,
        classification="requirement",
        certainty="explicit",
        evidence={"start": 0, "end": 4, "text": "gold"},
        raw_value="gold",
        normalized_values=("gold",),
        normalization_source="domain_dictionary",
        application="parser_candidate_ready",
        parser_update={"target": target, "value": value},
    )
    update, disposition = _prepare_candidate(
        candidate,
        (),
        dictionary=load_domain_dictionary(ROOT / "data/dictionary/v1.0.0.json"),
        locale="en",
    )
    assert update is None and disposition.reason == "component_target_not_representable"
