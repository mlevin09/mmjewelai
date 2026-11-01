"""F02 persisted HTTP normalization evidence on existing TEST-ONLY releases."""

import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from test_core_intent import _current, _immutable_history, _scenario, _submit
from test_f01_ownership import exercise_f01_case
from test_prompt_enrichment_composition import _client

F02_CASES = (
    (
        "F02-01",
        "A white gold ring with an oval diamond.",
        "en",
        {
            "metal.material": "gold",
            "metal.color": "white",
            "center_stone.material": "diamond",
            "center_stone.shape": "oval",
        },
    ),
    (
        "F02-02",
        "Кольцо из белого золота с овальным алмазом.",
        "ru",
        {
            "metal.material": "gold",
            "metal.color": "white",
            "center_stone.material": "diamond",
            "center_stone.shape": "oval",
        },
    ),
    (
        "F02-03",
        "White gold ring. Центральный овальный алмаз.",
        "ru",
        {
            "metal.material": "gold",
            "metal.color": "white",
            "center_stone.material": "diamond",
            "center_stone.shape": "oval",
        },
    ),
    (
        "F02-04",
        "A rose gold ring with an oval shape diamond.",
        "en",
        {
            "metal.material": "gold",
            "metal.color": "rose",
            "center_stone.material": "diamond",
            "center_stone.shape": "oval",
        },
    ),
    (
        "F02-05",
        "A gold ring with an emerald shape diamond.",
        "en",
        {
            "metal.material": "gold",
            "center_stone.material": "diamond",
            "center_stone.shape": "emerald_cut",
        },
    ),
    ("F02-07", "A gold three-stone ring.", "en", {"metal.material": "gold"}),
    ("F02-08", "A platinum ring with gold prongs.", "en", {"metal.material": "platinum"}),
    (
        "F02-09",
        "A gold ring with an oval diamond center stone and sapphire side stones.",
        "en",
        {
            "metal.material": "gold",
            "center_stone.material": "diamond",
            "center_stone.shape": "oval",
        },
    ),
    (
        "F02-10",
        "A matte platinum split-shank ring with an east-west blue sapphire.",
        "en",
        {"metal.material": "platinum"},
    ),
    (
        "F02-11",
        "Gold or platinum ring with an oval diamond.",
        "en",
        {"center_stone.material": "diamond", "center_stone.shape": "oval"},
    ),
    (
        "F02-12",
        "A gold ring is not what I want. Give me a platinum ring.",
        "en",
        {"metal.material": "platinum"},
    ),
    ("F02-13", "Maybe platinum. A ring.", "en", {}),
    ("F02-14", "A ruthenium ring.", "en", {}),
    ("control-unbound-palladium", "A palladium ring.", "en", {}),
    (
        "hyphen-cut",
        "A white-gold ring with an emerald-cut diamond.",
        "en",
        {
            "metal.material": "gold",
            "metal.color": "white",
            "center_stone.material": "diamond",
            "center_stone.shape": "emerald_cut",
        },
    ),
    (
        "ru-alias",
        "Кольцо из розового золота с овальным бриллиантом.",
        "ru",
        {
            "metal.material": "gold",
            "metal.color": "rose",
            "center_stone.material": "diamond",
            "center_stone.shape": "oval",
        },
    ),
    (
        "ru-deprecated",
        "Кольцо из золота с алмазом изумрудной формы.",
        "ru",
        {
            "metal.material": "gold",
            "center_stone.material": "diamond",
            "center_stone.shape": "emerald_cut",
        },
    ),
    (
        "category-cut",
        "A platinum ring with an emerald gemstone in a brilliant-cut center stone.",
        "en",
        {
            "metal.material": "platinum",
            "center_stone.material": "emerald",
            "center_stone.cut": "brilliant_cut",
        },
    ),
    (
        "negative-alias",
        "No rose gold. A platinum ring with an oval shape diamond.",
        "en",
        {
            "metal.material": "platinum",
            "center_stone.material": "diamond",
            "center_stone.shape": "oval",
        },
    ),
    ("preference-ru", "Хочу кольцо из белого золота с овальным бриллиантом.", "ru", {}),
)


@pytest.mark.parametrize("binding", (False, True))
@pytest.mark.parametrize("case", F02_CASES, ids=[c[0] for c in F02_CASES])
def test_f02_supported_http(engine, tmp_path, monkeypatch, binding, case):
    # Existing F01 helper checks each accepted state/source/description fact,
    # deferred relationships, no fabricated objects, exact history and restart.
    exercise_f01_case(engine, tmp_path, monkeypatch, case, binding)


LINEAGE_CASES = (
    (
        "en",
        "A gold ring with an emerald shape diamond.",
        "center_stone.shape",
        "emerald_cut",
        "deprecated_alias",
    ),
    (
        "ru",
        "Кольцо из золота с алмазом изумрудной формы.",
        "center_stone.shape",
        "emerald_cut",
        "deprecated_alias",
    ),
    (
        "ru",
        "Кольцо из розового золота с овальным бриллиантом.",
        "center_stone.material",
        "diamond",
        "synonym",
    ),
    ("en", "A rose gold ring with an oval shape diamond.", "center_stone.shape", "oval", "synonym"),
    (
        "en",
        "A gold ring. Алмаз изумрудной формы.",
        "center_stone.shape",
        "emerald_cut",
        "deprecated_alias",
    ),
    (
        "ru",
        "Кольцо из золота. An emerald shape diamond.",
        "center_stone.shape",
        "emerald_cut",
        "deprecated_alias",
    ),
    ("en", "A gold ring с бриллиантом.", "center_stone.material", "diamond", "synonym"),
)


def exercise_f02_lineage(engine, tmp_path, monkeypatch, binding, case):
    locale, text, target, canonical_id, kind = case
    with _scenario(engine, tmp_path, monkeypatch, binding=binding, locale=locale) as ctx:
        _, after, state, message = _submit(ctx, text)
        evaluated = ctx.evaluations[0][2]
        proposal = evaluated.parser_proposal
        accepted = next(u for u in proposal.accepted_updates if u.concrete_target == target)
        assert accepted.canonical_value == canonical_id and accepted.match_kind == kind
        warnings = [w for w in proposal.warnings if w.concrete_target == target]
        assert bool(warnings) is (kind == "deprecated_alias")
        if warnings:
            assert warnings[0].code == "DEPRECATED_ALIAS_USED"
        assert proposal.source.message_id == message["message_id"]
        assert proposal.dictionary_artifact_version == "1.0.0"
        disposition = next(d for d in evaluated.dispositions if d.concrete_target == target)
        assert disposition.outcome == "APPLIED"
        assert disposition.enrichment_proposal.provenance == "NORMALIZED_FROM_USER"
        assert disposition.enrichment_decision.result.value == canonical_id
        candidate = disposition.candidate
        assert accepted.candidate_value == candidate.parser_update.value
        assert text[candidate.evidence.start : candidate.evidence.end] == candidate.evidence.text
        # Initial runtime re-evaluates after the canonical transition. Alias
        # warnings must also survive a now-already-current target.
        current_proposal = ctx.evaluations[-1][2].parser_proposal
        if kind == "deprecated_alias":
            assert any(
                w.code == "DEPRECATED_ALIAS_USED" and w.concrete_target == target
                for w in current_proposal.warnings
            )
        output = state.final_output.model_dump(mode="json")
        history = _immutable_history(ctx)
        pin = ctx.repo.get_knowledge_release_pin(ctx.sid, ctx.org)
        print(
            "F02_LINEAGE "
            + json.dumps(
                {
                    "backend": engine.dialect.name,
                    "p010": binding,
                    "input": text,
                    "message_id": message["message_id"],
                    "candidate": candidate.model_dump(mode="json"),
                    "accepted": accepted.model_dump(mode="json"),
                    "warnings": [w.model_dump(mode="json") for w in warnings],
                    "release": state.knowledge_release.model_dump(mode="json"),
                },
                ensure_ascii=False,
            )
        )
    restarted, app, provider = _client(engine, ctx.config)
    with restarted:
        assert (
            restarted.get(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output", headers=ctx.headers
            ).json()
            == output
        )
        restored = app.state.prompt_enrichment_service
        assert restored.repository.get_current_revision(ctx.sid, ctx.org) == after
        assert restored.repository.get_knowledge_release_pin(ctx.sid, ctx.org) == pin
        assert (
            _immutable_history(SimpleNamespace(repo=restored.repository, sid=ctx.sid, org=ctx.org))
            == history
        )
        assert (
            restored.repository.get_message(ctx.sid, UUID(message["message_id"]), ctx.org).content
            == text
        )
        assert provider.calls == []


@pytest.mark.parametrize("binding", (False, True))
@pytest.mark.parametrize("case", LINEAGE_CASES)
def test_f02_alias_lineage_http(engine, tmp_path, monkeypatch, binding, case):
    exercise_f02_lineage(engine, tmp_path, monkeypatch, binding, case)


def test_locale_metadata_cannot_rebind_a_different_dictionary_value(engine, tmp_path, monkeypatch):
    from jewelai_parser import CandidateUpdate
    from jewelai_parser.models import TermCandidate

    from jewelai_api.parsed_enrichment import _retain_source_normalization

    with _scenario(engine, tmp_path, monkeypatch) as ctx:
        _submit(ctx, "A gold ring.")
        revision, _, evaluated = ctx.evaluations[0]
        proposal = evaluated.parser_proposal
        candidates = {
            d.concrete_target: d.candidate for d in evaluated.dispositions if d.concrete_target
        }
        candidates["metal.material"] = candidates["metal.material"].model_copy(
            update={
                "parser_update": CandidateUpdate(
                    target="metal.material", value=TermCandidate(text="платина")
                ),
            }
        )
        result = _retain_source_normalization(
            proposal, revision, candidates, ctx.runtime.artifacts.dictionary
        )
        # A foreign-language lookup proving platinum cannot annotate/rebind gold.
        assert result == proposal


def exercise_f02_knowledge_lineage(engine, tmp_path, monkeypatch, binding):
    from jewelai_parser.knowledge_matcher import KnowledgeLibraryMatcher

    with _scenario(engine, tmp_path, monkeypatch, binding=binding) as ctx:
        _, revision, state, message = _submit(ctx, "A gold three-stone ring.")
        parsed = ctx.evaluations[0][1]
        # These are distinct EXISTING concepts in the two selected fixtures.
        concept_id = "three_stone" if binding else "style.three_stone"
        candidate = next(
            c
            for c in parsed.candidates
            if c.normalization_source == "knowledge_library"
            and c.normalized_values == (concept_id,)
        )
        assert candidate.parser_update is None and revision.design.style is None
        original_runtime = ctx.runtime._load_release().compiled_runtime
        match = KnowledgeLibraryMatcher(original_runtime).match(
            candidate.evidence.text, locale="en"
        )
        assert match.outcome == "resolved"
        assert match.candidate.mapping_id == "LANG-EN-THREE-STONE"
        assert match.candidate.concept_id == concept_id
        evidence = next(
            e
            for e in state.clarification_plan.constraint_evidence
            if e.source_candidate_id == candidate.candidate_id
        )
        assert evidence.status == "unresolved" and evidence.canonical_target is None
        pin = ctx.repo.get_knowledge_release_pin(ctx.sid, ctx.org)
        output = state.final_output.model_dump(mode="json")
    restarted, app, provider = _client(engine, ctx.config)
    with restarted:
        runtime = app.state.prompt_enrichment_service
        restored = runtime.repository.restore_pinned_knowledge_runtime(
            ctx.sid,
            ctx.org,
            runtime.artifact_store,
            active_release=runtime.active_release,
            validation_report=runtime.validation_report,
        )
        stored_message = runtime.repository.get_message(
            ctx.sid, UUID(message["message_id"]), ctx.org
        )
        # Existing contracts retain raw spans + exact release graph, not a new
        # first-class durable mapping DTO. Re-resolve that immutable graph.
        surface = stored_message.content[candidate.evidence.start : candidate.evidence.end]
        assert (
            KnowledgeLibraryMatcher(restored.compiled_runtime).match(surface, locale="en") == match
        )
        concept = next(
            c
            for c in restored.compiled_runtime.domain_knowledge
            if c.concept_id == match.candidate.concept_id
        )
        assert concept.claim_ids == (("CLM-RING-STYLES",) if binding else ("CLM-THREE-STONE",))
        claim = next(
            c for c in restored.compiled_runtime.claims if c.claim_id == concept.claim_ids[0]
        )
        assert claim.source_id == (
            "SRC-GIA-RING-SETTINGS-2026" if binding else "SRC-THREE-STONE-VALIDATION"
        )
        assert runtime.repository.get_knowledge_release_pin(ctx.sid, ctx.org) == pin
        assert (
            restarted.get(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output", headers=ctx.headers
            ).json()
            == output
        )
        assert provider.calls == []
        print(
            "F02_KNOWLEDGE_LINEAGE "
            + json.dumps(
                {
                    "backend": engine.dialect.name,
                    "p010": binding,
                    "message_id": message["message_id"],
                    "candidate": candidate.model_dump(mode="json"),
                    "match": match.model_dump(mode="json"),
                    "claim_id": claim.claim_id,
                    "source_id": claim.source_id,
                    "runtime_sha256": restored.runtime_sha256,
                    "restart_mapping_identical": True,
                }
            )
        )


@pytest.mark.parametrize("binding", (False, True))
def test_f02_knowledge_only_pinned_graph_restart(engine, tmp_path, monkeypatch, binding):
    exercise_f02_knowledge_lineage(engine, tmp_path, monkeypatch, binding)


def exercise_f02_correction(engine, tmp_path, monkeypatch, binding):
    from uuid import uuid4

    from test_prompt_enrichment_http import _message

    with _scenario(engine, tmp_path, monkeypatch, binding=binding, locale="ru") as ctx:
        _, initial, state, initial_message = _submit(ctx, "Кольцо из золота с овальным алмазом.")
        initial_history = _immutable_history(ctx)
        pin = ctx.repo.get_knowledge_release_pin(ctx.sid, ctx.org)
        _, corrected, state, alias_message = _submit(ctx, "Алмаз изумрудной формы.", "corrections")
        evaluation = ctx.evaluations[-2][2]
        # Correction orchestration records both before- and after-transition evaluations.
        accepted = [
            u
            for u in evaluation.parser_proposal.accepted_updates
            if u.concrete_target == "center_stone.shape"
        ]
        assert accepted and accepted[0].match_kind == "deprecated_alias"
        assert any(w.code == "DEPRECATED_ALIAS_USED" for w in evaluation.parser_proposal.warnings)
        assert corrected.design.center_stone.shape.value == "emerald_cut"
        assert corrected.design.center_stone.shape.source.message_id == alias_message["message_id"]
        assert corrected.design.metal.material == initial.design.metal.material
        assert corrected.design.center_stone.material == initial.design.center_stone.material
        _, _, state, _ = _submit(ctx, "Предпочитаю белый цвет металла.", "corrections")
        question = next(q for q in state.clarification_plan.questions if q.target == "metal.color")
        answer_message = _message(ctx.client, str(ctx.sid), str(ctx.org), "белый")
        response = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
            headers=ctx.headers,
            json={
                "clarification_plan_id": str(state.clarification_plan_id),
                "clarification_id": question.clarification_id,
                "decision": "ACCEPT",
                "answer_id": str(uuid4()),
                "expected_revision_id": str(state.authoritative_revision_id),
                "message_id": answer_message["message_id"],
            },
        )
        assert response.status_code == 200, response.json()
        final_revision = _current(ctx)
        assert final_revision.design.metal.color.value == "white"
        assert final_revision.design.center_stone.shape == corrected.design.center_stone.shape
        final = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output", headers=ctx.headers
        )
        assert final.status_code == 200
        output = final.json()
        facts = {f["target"]: f for f in output["internal_final_prompt"]["design_facts"]}
        assert facts["center_stone.shape"]["value"] == "emerald_cut"
        assert alias_message["message_id"] in facts["center_stone.shape"]["source_ids"]
        history = _immutable_history(ctx)
        for collection, records in initial_history.items():
            assert all(history[collection].get(k) == v for k, v in records.items())
        stale = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections",
            headers=ctx.headers,
            json={
                "message_id": initial_message["message_id"],
                "expected_revision_id": str(initial.revision_id),
            },
        )
        assert stale.status_code == 409 and _immutable_history(ctx) == history
        assert ctx.repo.get_knowledge_release_pin(ctx.sid, ctx.org) == pin
    restarted, app, provider = _client(engine, ctx.config)
    with restarted:
        result = restarted.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output", headers=ctx.headers
        )
        assert result.status_code == 200 and result.json() == output
        restored = app.state.prompt_enrichment_service
        assert restored.repository.get_current_revision(ctx.sid, ctx.org) == final_revision
        assert restored.repository.get_knowledge_release_pin(ctx.sid, ctx.org) == pin
        assert (
            _immutable_history(SimpleNamespace(repo=restored.repository, sid=ctx.sid, org=ctx.org))
            == history
        )
        assert provider.calls == []


@pytest.mark.parametrize("binding", (False, True))
def test_f02_correction_clarification_restart(engine, tmp_path, monkeypatch, binding):
    exercise_f02_correction(engine, tmp_path, monkeypatch, binding)
