"""Focused positive-journey acceptance reproducers; no provider calls."""

import json
import os
from pathlib import Path

import pytest
from jewelai_parser import full_message
from test_f04_http import f04_session, restart
from test_f05_admission import admit
from test_f05_history import READY, initial
from test_f05_preservation_polarity import submit
from test_f05_preview import output, state
from test_f05_release_http import answer3, correct3

from jewelai_api import continuation_evaluation, prompt_enrichment_runtime_v2


@pytest.mark.parametrize("journey", ["J4", "J5", "J7"])
def test_positive_completion_minimal_http(engine, tmp_path, journey, monkeypatch):
    locale = "en" if journey == "J4" else "ru"
    text = (
        "Кольцо из белого золота. Овальный центральный алмаз в крапановой закрепке. "
        "Центральный камень 8 x 6 x 4 мм."
        if journey == "J7"
        else "Кольцо из белого золота. Oval diamond center stone in prong setting. "
        "Центральный камень 8 x 6 x 4 мм."
        if journey == "J5"
        else READY.replace(" Keep the center stone unchanged.", "")
    )
    with f04_session(engine, tmp_path, locale=locale, binding=True) as ctx:
        assert (
            prompt_enrichment_runtime_v2.parse_full_message
            is continuation_evaluation.parse_full_message
            is full_message.parse_full_message
        )
        extraction_inputs = []
        extract = full_message._lexical_candidates

        def observe_extraction(source_text, *args):
            extraction_inputs.append(source_text)
            return extract(source_text, *args)

        monkeypatch.setattr(full_message, "_lexical_candidates", observe_extraction)
        captured = []
        service_type = type(ctx.runtime)
        actual = service_type.start_initial_message

        def observe(service, *args, **kwargs):
            result = actual(service, *args, **kwargs)
            captured.append(result.parse_result.model_dump(mode="json"))
            return result

        monkeypatch.setattr(service_type, "start_initial_message", observe)
        initial(ctx, "F", text)
        initial_revision = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        assert initial_revision.design.center_stone.material.value == "diamond"
        assert initial_revision.design.center_stone.shape.value == "oval"
        assert initial_revision.design.center_stone.setting.value == "prong_setting"
        dimensions = initial_revision.design.center_stone.dimensions.value
        assert (dimensions.length.value, dimensions.width.value, dimensions.depth.value) == (
            8,
            6,
            4,
        )
        ctx.runtime.continuation_enabled = True
        response, _ = admit(ctx)
        assert response.status_code == 201, response.json()
        correction_text = (
            "Keep the center stone unchanged."
            if journey == "J4"
            else "Кольцо из жёлтой платины."
            if journey == "J5"
            else "Кольцо из платины."
        )
        changed = submit(ctx, correction_text)["current_state"]
        intermediate = output(ctx, changed, projection=False)
        assert intermediate.status_code == 200, intermediate.json()
        if journey == "J4":
            assert len(changed["protection_projection"]["roots"]) == 1
            assert "Unaccepted source request" not in intermediate.json()["description"]["text"]
            pending = correct3(ctx, changed, "Emerald cut center stone.")
            offer = next(
                q["offer"] for q in pending["questions"] if q["question_kind"] == "KEEP_RELEASE"
            )
            changed = answer3(ctx, pending, offer, "ACCEPT")
        elif journey == "J5":
            assert "Принятые текущие факты" in intermediate.json()["description"]["text"]
            assert (
                "дополнительная неуточнённая интерпретация"
                in intermediate.json()["description"]["text"]
            )
            changed = correct3(ctx, changed, "Кольцо из жёлтого золота.")
        current = state(ctx)
        assert current == changed
        assert text in extraction_inputs and correction_text in extraction_inputs
        final = output(ctx, current, projection=False)
        assert final.status_code == 200, final.json()
        revision = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        if journey == "J4":
            assert revision.design.center_stone.shape.value == "emerald_cut"
            for field in type(initial_revision.design.center_stone).model_fields:
                if field != "shape":
                    assert getattr(revision.design.center_stone, field) == getattr(
                        initial_revision.design.center_stone, field
                    )
        elif journey == "J5":
            assert revision.design.metal.material.value == "gold"
            assert revision.design.metal.color.value == "yellow"
            assert (
                "Ранее принятые факты из этого сообщения заменены"
                in final.json()["description"]["text"]
            )
        else:
            assert revision.design.metal.material.value == "platinum"
        assert (
            journey == "J4" or revision.design.center_stone == initial_revision.design.center_stone
        )
        committed = (
            ctx.repo.list_revisions(ctx.sid, ctx.org),
            ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org),
            ctx.repo.list_clarification_plans(ctx.sid, ctx.org),
        )
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            assert state(ctx) == current
            assert output(ctx, current, projection=False).json() == final.json()
            assert ctx.repo.get_current_revision(ctx.sid, ctx.org) == revision
            assert (
                ctx.repo.list_revisions(ctx.sid, ctx.org),
                ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org),
                ctx.repo.list_clarification_plans(ctx.sid, ctx.org),
            ) == committed
        evidence = dict(
            journey=journey,
            original_input=text,
            initial_parse=captured,
            initial_canonical=initial_revision.model_dump(mode="json"),
            correction_text=correction_text,
            intermediate_output=intermediate.json(),
            same_parser_extraction_inputs=extraction_inputs,
            restart_identical=True,
            state=current,
            canonical=revision.model_dump(mode="json"),
            final_output=final.json(),
            provider_calls=len(ctx.provider.calls),
        )
        folder = os.getenv("F05_COMPLETION_EVIDENCE_DIR")
        if folder:
            dest = Path(folder)
            dest.mkdir(parents=True, exist_ok=True)
            (dest / f"{journey}.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2)
            )
        assert ctx.provider.calls == []
        description = final.json()["description"]["text"]
        if journey == "J4":
            assert len(current["protection_projection"]["roots"]) == 1
            assert "Unaccepted source request: «Keep the center stone unchanged»" not in description
        elif journey == "J5":
            assert revision.design.metal.material.value == "gold"
            assert revision.design.metal.color.value == "yellow"
            assert "Непринятый исходный запрос: «Кольцо из жёлтой платины»" not in description
        else:
            assert revision.design.center_stone.material.value == "diamond"
