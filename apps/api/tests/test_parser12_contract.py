"""One current parse contract across actual native writers and persisted restart."""

import importlib
import json
import os
from pathlib import Path

import pytest
from test_f04_http import f04_session, restart
from test_f05_admission import admit
from test_f05_history import initial
from test_f05_preview import output, state
from test_f05_release_http import correct3
from test_prompt_enrichment_http import _message

from jewelai_api.correction_enrichment import decode_correction_result


@pytest.fixture
def current_parse_calls(monkeypatch):
    calls = []
    for name in (
        "prompt_enrichment_runtime",
        "prompt_enrichment_runtime_v2",
        "correction_enrichment",
        "continuation_evaluation",
        "conflict_evidence",
        "compatibility_projection",
    ):
        module = importlib.import_module(f"jewelai_api.{name}")
        actual = module.parse_full_message

        def observe(*args, _actual=actual, _name=name, **kwargs):
            parsed = _actual(*args, **kwargs)
            assert parsed.parse_version == "1.2.0", _name
            calls.append(_name)
            return parsed

        monkeypatch.setattr(module, "parse_full_message", observe)
    return calls


@pytest.mark.parametrize(
    "base,locale,text,correction",
    [
        ("L", "en", "A white gold ring.", "A platinum ring."),
        ("F", "en", "A white gold ring.", "A platinum ring."),
        ("F", "ru", "Кольцо из белого золота.", "Кольцо из платины."),
        ("F", "ru", "A white gold кольцо.", "A platinum кольцо."),
    ],
)
def test_current_initial_native_correction_and_restart(
    engine, tmp_path, current_parse_calls, base, locale, text, correction
):
    with f04_session(engine, tmp_path, locale=locale) as ctx:
        initial(ctx, base, text)
        initial_module = (
            "prompt_enrichment_runtime" if base == "L" else "prompt_enrichment_runtime_v2"
        )
        assert initial_module in current_parse_calls
        original = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        state = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/state", headers=ctx.headers
        )
        assert state.status_code == 200, state.json()
        message = _message(ctx.client, str(ctx.sid), str(ctx.org), correction)
        payload = dict(
            expected_revision_id=str(original.revision_id), message_id=message["message_id"]
        )
        if base == "F":
            payload.update(
                schema_version="2.0.0",
                expected_enrichment_cycle_id=state.json()["enrichment_cycle_id"],
                expected_enrichment_result_hash=ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)[
                    -1
                ].result.content_hash,
                expected_clarification_plan_hash=state.json()["clarification_plan_content_hash"],
            )
        response = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections",
            headers=ctx.headers,
            json=payload,
        )
        assert response.status_code == 200, response.json()
        current = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        assert current.design.metal.material.value == "platinum"
        assert current.design.center_stone == original.design.center_stone
        records = ctx.repo.list_user_corrections(ctx.sid, ctx.org)
        assert len(records) == 1
        record = records[0].result_payload
        for parsed in (
            record["parsed_correction"],
            record["correction_evaluation"]["parse_result"],
            record["post_transition_evaluation"]["parse_result"],
        ):
            assert parsed["parse_version"] == "1.2.0"
        restored_dto = decode_correction_result(record)
        assert restored_dto.model_dump(mode="json") == record
        with restart(ctx, engine):
            restored = ctx.client.get(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/state", headers=ctx.headers
            )
            assert restored.status_code == 200, restored.json()
            assert restored.json() == response.json()["state"]
            assert ctx.repo.get_current_revision(ctx.sid, ctx.org) == current
            assert ctx.repo.list_user_corrections(ctx.sid, ctx.org)[0].result_payload == record
        assert "correction_enrichment" in current_parse_calls
        assert ctx.provider.calls == []


def test_new_continuation_and_resumed_request_use_current_parse(
    engine, tmp_path, current_parse_calls
):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, "F")
        ctx.runtime.continuation_enabled = True
        admitted, _ = admit(ctx)
        assert admitted.status_code == 201, admitted.json()
        original = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        changed = correct3(ctx, state(ctx), "A platinum ring.")
        assert "continuation_evaluation" in current_parse_calls
        rows = ctx.repo.list_user_corrections(ctx.sid, ctx.org)
        assert rows[-1].result_payload["correction_version"] == "3.0.0"
        assert (
            rows[-1].result_payload["correction_evaluation"]["parse_result"]["parse_version"]
            == "1.2.0"
        )
        assert rows[-1].result_payload["source_parse"]["parse_version"] == "1.2.0"
        final = output(ctx, changed, projection=False)
        assert final.status_code == 200, final.json()
        assert "platinum" in final.json()["description"]["text"]
        assert final.json()["internal_final_prompt"]["protection_projection"]["roots"]
        assert any(
            c["kind"] == "preservation"
            for c in final.json()["internal_final_prompt"]["constraints"]
        )
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            assert state(ctx) == changed
            assert output(ctx, changed, projection=False).json() == final.json()
            calls_before = len(current_parse_calls)
            resumed = correct3(ctx, changed, "A yellow gold ring.")
            assert "continuation_evaluation" in current_parse_calls[calls_before:]
            current = ctx.repo.get_current_revision(ctx.sid, ctx.org)
            assert current.design.metal.material.value == "gold"
            assert current.design.center_stone == original.design.center_stone
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            assert state(ctx) == resumed
        assert ctx.provider.calls == []
        folder = os.getenv("PARSER12_EVIDENCE_DIR")
        if folder:
            root = Path(folder)
            root.mkdir(parents=True, exist_ok=True)
            (root / "current-continuation-restart.json").write_text(
                json.dumps(
                    dict(
                        backend=engine.dialect.name,
                        initial_revision=original.model_dump(mode="json"),
                        correction_record=rows[-1].result_payload,
                        output=final.json(),
                        resumed_state=resumed,
                        resumed_revision=current.model_dump(mode="json"),
                        restart_equal=True,
                        observed_parse_version="1.2.0",
                        observed_calls=current_parse_calls,
                        provider_calls=0,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
