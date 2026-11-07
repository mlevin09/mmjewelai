"""Scoped Studio current-state and pending-decision HTTP evidence; no providers."""

import pytest
import test_f04_http as f04
from conftest import ROOT
from test_conversation import correct, read
from test_f05_history import initial
from test_preprod_no_defaults import preprod_enabled as preprod_enabled
from test_prompt_completion import command


@pytest.fixture
def core_release(monkeypatch):
    # Existing immutable source, local SYNTHETIC release only; no professional promotion.
    from tools.knowledge.build_recovered_draft import project_core

    original = f04._release
    payload = project_core((ROOT / "data/knowledge/v1/jewelry-core-1.0.0.json").read_bytes())
    monkeypatch.setattr(
        f04, "_release", lambda tmp, **kw: original(tmp, bundle=payload.model_dump(mode="json"))
    )


def test_mixed_owner_update_reports_unapplied_replacements(
    engine, tmp_path, preprod_enabled, core_release
):
    with f04.f04_session(engine, tmp_path, locale="ru") as ctx:
        initial(ctx, "F", "Кольцо из белого золота с овальным центральным бриллиантом.")
        before = read(ctx)
        text = (
            "Jewelry type: Браслет\nMetal: Платина\n"
            "Center stone: Без центрального камня\nStyle and finish: Матовая отделка"
        )
        after = correct(ctx, before, text)
        design = after["revision"]["design"]
        assert design["metal"]["material"]["value"] == "platinum"
        assert design["jewelry_type"] == before["revision"]["design"]["jewelry_type"]
        assert design["center_stone"] == before["revision"]["design"]["center_stone"]
        record = ctx.repo.list_user_corrections(ctx.sid, ctx.org)[-1]
        refused = next(
            d
            for d in record.result_payload["correction_evaluation"]["dispositions"]
            if d["candidate"]["evidence"]["text"] == "Браслет"
        )
        assert refused["reason"] == "target_not_supported_by_parser"
        event = next(e for e in after["events"] if e["kind"] == "decision")
        assert event["outcome"] == "APPLIED"  # Partial application is not blanket acceptance.
        assert "Не применено" in event["text"]
        assert "тип украшения" in event["text"]
        assert "не поддерживает" in event["text"]
        assert "металл" not in event["text"].split("Не применено", 1)[1]
        _, done = command(ctx, after)
        assert done.status_code == 200, done.json()
        assert done.json()["final_prompt"]["canonical_revision"]["design"] == design
        assert not done.json()["final_prompt"]["assumptions"]
        assert ctx.provider.calls == []


@pytest.mark.parametrize(
    "locale,text,expected_label",
    [
        ("en", "Jewelry type: pendant\nMetal: platinum\nStyle: minimalist", "pendant"),
        ("ru", "Jewelry type: Подвеска\nMetal: Платина\nStyle: Минимализм", "подвеска"),
    ],
)
def test_supported_same_session_replacement_and_restart(
    engine, tmp_path, preprod_enabled, locale, text, expected_label
):
    from test_f04_http import restart

    with f04.f04_session(engine, tmp_path, locale=locale) as ctx:
        initial(ctx, "F", "A white gold ring with an oval diamond center stone in prong setting.")
        before = read(ctx)
        after = correct(ctx, before, text)
        design = after["revision"]["design"]
        assert design["jewelry_type"]["value"] == "pendant"
        assert design["metal"]["material"]["value"] == "platinum"
        assert design["style"]["value"] == ["minimalist"]
        assert design["center_stone"] == before["revision"]["design"]["center_stone"]
        assert expected_label in after["state"]["description"]["text"]
        # Original request/history remains immutable, it is not the new canonical fact.
        assert any("ring" in e["text"] for e in after["events"] if e["kind"] == "user")
        with restart(ctx, engine):
            assert read(ctx) == after
        assert ctx.provider.calls == []


def test_setting_and_atomic_dimension_contracts(engine, tmp_path, preprod_enabled):
    from test_f04_http import restart

    with f04.f04_session(engine, tmp_path, locale="ru") as ctx:
        initial(
            ctx,
            "F",
            "Кольцо из золота с овальным центральным бриллиантом. Центральный камень 8 x 6 x 4 мм.",
        )
        state = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/state", headers=ctx.headers
        ).json()
        question = next(
            q
            for q in state["clarification_questions"]
            if q["semantic_question_id"] == "CENTER_STONE_SETTING"
        )
        assert (
            "UNKNOWN" in question["allowed_decisions"] and "SKIP" in question["allowed_decisions"]
        )
        # allowed_decisions is not an option catalog. SELECT_OPTION still
        # requires an actually offered option ID/value; no options are invented.
        before = read(ctx)
        unsupported = correct(ctx, before, "Центральный камень: безель.")
        assert unsupported["revision"]["design"]["center_stone"]["setting"] is None
        known = correct(ctx, unsupported, "Центральный камень: крапановая закрепка.")
        setting = known["revision"]["design"]["center_stone"]["setting"]
        assert setting["value"] == "prong_setting" and setting["origin"] == "explicit"
        original_dimensions = known["revision"]["design"]["center_stone"]["dimensions"]
        for partial in ("Длина центрального камня 9 мм.", "Центральный камень 9 x 7 мм."):
            known = correct(ctx, known, partial)
            assert known["revision"]["design"]["center_stone"]["dimensions"] == original_dimensions
            assert known["revision"]["design"]["center_stone"]["setting"] == setting
        full = correct(ctx, known, "Центральный камень 9 x 7 x 5 мм.")
        dimensions = full["revision"]["design"]["center_stone"]["dimensions"]
        assert [dimensions["value"][axis] for axis in ("length", "width", "depth")] == [
            {"value": v, "unit": "mm"} for v in (9, 7, 5)
        ]
        assert dimensions["origin"] == "explicit"
        with restart(ctx, engine):
            assert read(ctx) == full
        assert ctx.provider.calls == []


@pytest.mark.parametrize(
    "locale,text,expected_style,unresolved_request",
    [
        (
            "en",
            "Center stone: No center stone\nStyle: Minimalist",
            "minimalist",
            "Center stone: No center stone",
        ),
        (
            "ru",
            "Центральный камень: Без центрального камня\nСтиль: Минимализм",
            "minimalist",
            "Центральный камень: Без центрального камня",
        ),
        (
            "ru",
            "Center stone: Без центрального камня\nStyle: Минимализм",
            "minimalist",
            "Center stone: Без центрального камня",
        ),
        ("en", "Center stone -8 x 6 x 4 mm", None, None),
        ("en", "No center stone", None, "No center stone"),
        ("ru", "Без центрального камня", None, "Без центрального камня"),
    ],
    ids=[
        "absence-en",
        "absence-ru",
        "absence-mixed",
        "negative-dimensions",
        "absence-alone-en",
        "absence-alone-ru",
    ],
)
def test_source_boundaries_current_correction_restart_and_final(
    engine,
    tmp_path,
    preprod_enabled,
    core_release,
    locale,
    text,
    expected_style,
    unresolved_request,
):
    from test_f04_http import restart
    from test_prompt_completion import current

    with f04.f04_session(engine, tmp_path, locale=locale) as ctx:
        initial(ctx, "F", "A white gold ring with an oval diamond center stone in prong setting.")
        before = read(ctx)
        after = correct(ctx, before, text)
        design = after["revision"]["design"]
        assert design["center_stone"] == before["revision"]["design"]["center_stone"]
        if expected_style:
            assert design["style"]["value"] == [expected_style]
        else:
            assert design["center_stone"]["dimensions"] is None
        row = next(
            r
            for r in ctx.repo.list_user_corrections(ctx.sid, ctx.org)
            if r.result_payload["correction_text"] == text
        )
        parsed = row.result_payload["parsed_correction"]
        assert parsed["parse_version"] == "1.3.0"
        assert (
            row.result_payload["post_transition_evaluation"]["enrichment_result"][
                "parser_evidence_version"
            ]
            == "1.3.0"
        )
        if unresolved_request:
            candidates = [
                c for c in parsed["candidates"] if c["evidence"]["text"] == unresolved_request
            ]
            assert len(candidates) == 1  # One complete request, not isolated noun fragments.
            candidate = candidates[0]
            assert candidate["classification"] == "prohibition"
            assert candidate["certainty"] == "unresolved"
            assert candidate["target"] is None and candidate["parser_update"] is None
            span = candidate["evidence"]
            assert text[span["start"] : span["end"]] == unresolved_request
            disposition = next(
                d
                for d in row.result_payload["correction_evaluation"]["dispositions"]
                if d["candidate"]["candidate_id"] == candidate["candidate_id"]
            )
            assert disposition["outcome"] == "DEFERRED"
            event = next(
                e
                for e in after["events"]
                if e["event_id"] == "decision:" + str(row.correction_record_id)
            )
            assert event["text"] != "APPLIED"
            assert unresolved_request in event["text"]
            assert ("Не применено" if locale == "ru" else "Not applied") in event["text"]
            assert event["outcome"] == ("APPLIED" if expected_style else "DEFERRED")
            if not expected_style:
                assert after["revision"] == before["revision"]
            assert unresolved_request in after["state"]["description"]["text"]
        with restart(ctx, engine):
            assert read(ctx) == after
        _, done = command(ctx, after)
        assert done.status_code == 200, done.json()
        final = done.json()["final_prompt"]
        assert final["canonical_revision"]["design"] == design
        if unresolved_request:
            evidence = [
                e
                for e in final["base_prompt"]["constraint_evidence"]
                if e["original_wording"] == unresolved_request
            ]
            assert len(evidence) == 1
            item = evidence[0]
            assert item["status"] == "unresolved" and item["acceptance"] == "unresolved"
            assert item["canonical_target"] is None and item["normalized_instruction"] is None
            assert item["source"] == row.result_payload["source"]
            assert item["source_candidate_id"] == candidate["candidate_id"]
            assert (item["source_span_start"], item["source_span_end"]) == (
                span["start"],
                span["end"],
            )
            assert unresolved_request in final["base_prompt"]["prompt_text"]
            assert not final["assumptions"]
        with restart(ctx, engine):
            assert current(ctx).json()["final_prompt"] == final
            assert read(ctx)["revision"] == after["revision"]
        assert ctx.provider.calls == []


@pytest.mark.parametrize("version", ["1.1.0", "1.2.0"])
def test_historical_source_keeps_original_hashes_then_accepts_current_parser(
    engine, tmp_path, preprod_enabled, core_release, monkeypatch, version
):
    import importlib

    from jewelai_domain.clarification_state import evidence_bytes
    from jewelai_parser.full_message import _parse_recorded_message, _source_governance
    from test_f04_http import restart

    def historical_source(text, **kwargs):
        return _parse_recorded_message(text, parse_version=version, **kwargs)

    with f04.f04_session(engine, tmp_path) as ctx:
        # Test-only historical seed. No active endpoint accepts a version selector.
        with monkeypatch.context() as patch, _source_governance(version):
            for name in ("prompt_enrichment_runtime_v2", "correction_enrichment"):
                patch.setattr(
                    importlib.import_module("jewelai_api." + name),
                    "parse_full_message",
                    historical_source,
                )
            initial(
                ctx, "F", "A white gold ring with an oval diamond center stone in prong setting."
            )
            old = correct(ctx, read(ctx), "Center stone: No center stone\nStyle: minimalist")
            assert old["revision"]["design"]["style"] is None
        old_records = ctx.repo.list_user_corrections(ctx.sid, ctx.org)
        old_cycles = ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)
        hashes = {r.correction_record_id: r.content_hash for r in old_records}
        payloads = {r.correction_record_id: evidence_bytes(r.result_payload) for r in old_records}
        cycle_payloads = [evidence_bytes(c.result) for c in old_cycles]
        assert all(
            "parser_evidence_version" not in c.result.model_dump(mode="json") for c in old_cycles
        )
        with restart(ctx, engine):
            assert read(ctx) == old
            changed = correct(ctx, old, "Style: minimalist")
            assert changed["revision"]["design"]["style"]["value"] == ["minimalist"]
        with restart(ctx, engine):
            assert read(ctx) == changed
        rows = ctx.repo.list_user_corrections(ctx.sid, ctx.org)
        assert {
            r.correction_record_id: r.content_hash for r in rows if r.correction_record_id in hashes
        } == hashes
        assert {
            r.correction_record_id: evidence_bytes(r.result_payload)
            for r in rows
            if r.correction_record_id in payloads
        } == payloads
        assert [
            evidence_bytes(c.result)
            for c in ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)[: len(old_cycles)]
        ] == cycle_payloads
        assert (
            len(
                [
                    r
                    for r in rows
                    if r.result_payload["parsed_correction"]["parse_version"] == "1.3.0"
                ]
            )
            == 1
        )
        _, done = command(ctx, changed)
        assert done.status_code == 200, done.json()
        assert (
            done.json()["final_prompt"]["canonical_revision"]["design"]
            == changed["revision"]["design"]
        )


def test_historical_keep_release_restores_then_new_continuation_uses_parser13(
    engine, tmp_path, monkeypatch
):
    import importlib

    from jewelai_domain.clarification_state import evidence_bytes
    from jewelai_parser.full_message import _parse_recorded_message, _source_governance
    from test_f04_http import restart
    from test_f05_mutation_safety import answer3, pending_fixture
    from test_f05_preview import output, state
    from test_f05_release_http import correct3

    def historical_source(text, **kwargs):
        return _parse_recorded_message(text, parse_version="1.2.0", **kwargs)

    with f04.f04_session(engine, tmp_path) as ctx:
        with monkeypatch.context() as patch, _source_governance("1.2.0"):
            for name in ("prompt_enrichment_runtime_v2", "continuation_evaluation"):
                patch.setattr(
                    importlib.import_module("jewelai_api." + name),
                    "parse_full_message",
                    historical_source,
                )
            from jewelai_api import continuation_answers, continuation_corrections

            original_correction = continuation_corrections.prepare_correction
            original_answer = continuation_answers.prepare_answer

            def seed_correction(*args, **kwargs):
                kwargs["_recorded_parse_version"] = "1.2.0"
                return original_correction(*args, **kwargs)

            def seed_answer(*args, **kwargs):
                kwargs["_recorded_governance_version"] = "1.2.0"
                return original_answer(*args, **kwargs)

            patch.setattr(continuation_corrections, "prepare_correction", seed_correction)
            patch.setattr(continuation_answers, "prepare_answer", seed_answer)
            current, offer = pending_fixture(ctx, "F")
            current = answer3(ctx, current, offer, "ACCEPT")
        saved = {
            r.correction_record_id: evidence_bytes(r.result_payload)
            for r in ctx.repo.list_user_corrections(ctx.sid, ctx.org)
        }
        answers = {
            r.answer_record_id: evidence_bytes(r.result_payload)
            for r in ctx.repo.list_clarification_answers(ctx.sid, ctx.org)
        }
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            assert state(ctx) == current
            assert output(ctx, current, projection=False).status_code == 200
            changed = correct3(ctx, current, "A platinum ring.")
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            assert state(ctx) == changed
        rows = ctx.repo.list_user_corrections(ctx.sid, ctx.org)
        assert {
            r.correction_record_id: evidence_bytes(r.result_payload)
            for r in rows
            if r.correction_record_id in saved
        } == saved
        assert {
            r.answer_record_id: evidence_bytes(r.result_payload)
            for r in ctx.repo.list_clarification_answers(ctx.sid, ctx.org)
        } == answers
        assert (
            len([r for r in rows if r.result_payload["source_parse"]["parse_version"] == "1.3.0"])
            == 1
        )
        assert ctx.provider.calls == []


@pytest.mark.parametrize("decision", ["UNKNOWN", "SKIP"])
def test_dimension_nonvalue_decision_never_invents_measurements(
    engine, tmp_path, preprod_enabled, decision
):
    from test_f04_http import answer_question, restart

    with f04.f04_session(engine, tmp_path) as ctx:
        initial(ctx, "F", "A white gold ring with an oval diamond center stone in prong setting.")
        before = read(ctx)
        state = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/state", headers=ctx.headers
        ).json()
        question = next(
            q
            for q in state["clarification_questions"]
            if q["semantic_question_id"] == "CENTER_STONE_DIMENSIONS"
        )
        response = answer_question(ctx, state, question, decision)
        assert response.status_code == 200, response.json()
        after = read(ctx)
        assert after["revision"] == before["revision"]
        assert after["revision"]["design"]["center_stone"]["dimensions"] is None
        record = ctx.repo.list_clarification_answers(ctx.sid, ctx.org)[-1].result_payload
        assert record["decision"] == decision
        with restart(ctx, engine):
            assert read(ctx) == after
        assert ctx.provider.calls == []
