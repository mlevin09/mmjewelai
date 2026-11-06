"""Actual preprod policy: no professional defaults, persisted existing HTTP flow."""

import re
from functools import partial

import pytest
import test_prompt_enrichment_composition as composition
from conftest import ROOT
from jewelai_prompts.completion import CompletionRegistry
from test_conversation import correct, read
from test_f04_http import f04_session, restart
from test_f05_history import initial
from test_prompt_completion import command, current

from jewelai_api.completion import load_registry

POLICY = ROOT / "data/completion/preprod-no-defaults-1.0.0.json"


def policy():
    registry = CompletionRegistry.model_validate_json(POLICY.read_bytes())
    return load_registry(POLICY, registry.sha256)


@pytest.fixture
def preprod_enabled(monkeypatch):
    monkeypatch.setattr(
        composition, "create_app", partial(composition.create_app, completion_registry=policy())
    )


def test_preprod_pin_and_packaging_fail_closed():
    registry = policy()
    assert registry.review_status == "APPROVED"
    assert not registry.rules
    assert {e.target for e in registry.eligibility} == {
        "center_stone.dimensions",
        "center_stone.setting",
        "center_stone.cut",
        "metal.color",
    }
    assert all(e.mode == "default_or_omit" for e in registry.eligibility)
    service = (ROOT / "infra/terraform/preprod/services.tf").read_text()
    assert re.search(rf'PROMPT_COMPLETION_POLICY_SHA256\s*=\s*"{registry.sha256}"', service)
    assert f'"/app/{POLICY.relative_to(ROOT)}"' in service
    assert "COPY data /app/data" in (ROOT / "infra/docker/api.Dockerfile").read_text()
    with pytest.raises(ValueError, match="SHA-256"):
        load_registry(POLICY, "0" * 64)
    proposed_path = ROOT / "data/completion/proposed-1.0.0.json"
    proposed = CompletionRegistry.model_validate_json(proposed_path.read_bytes())
    with pytest.raises(ValueError, match="approval"):
        load_registry(proposed_path, proposed.sha256)


@pytest.mark.parametrize(
    "locale,text,change,next_change",
    [
        (
            "en",
            "A gold ring with an oval diamond center stone.",
            "Use a prong setting.",
            "Use white gold.",
        ),
        (
            "ru",
            "Кольцо из золота с овальным центральным бриллиантом.",
            "Используй крапановую закрепку.",
            "Используй белое золото.",
        ),
    ],
)
def test_real_policy_yes_no_restart_invalidation_without_defaults(
    engine, tmp_path, preprod_enabled, locale, text, change, next_change
):
    with f04_session(engine, tmp_path, binding=True, locale=locale) as ctx:
        initial(ctx, "F", text)
        assert current(ctx).json()["status"] == "AWAITING_COMPLETION"
        _, yes = command(ctx, read(ctx), "YES")
        assert yes.status_code == 200, yes.json()
        assert yes.json()["status"] == "EDITING"
        state = correct(ctx, read(ctx), change)
        before = read(ctx)
        _, no = command(ctx, state)
        assert no.status_code == 200, no.json()
        final = no.json()["final_prompt"]
        assert final["schema_version"] == "6.0.0"
        assert final["assumptions"] == []
        assert final["canonical_revision"] == final["effective_revision"]
        assert "center_stone.dimensions" in final["omitted_targets"]
        assert "LEFT UNSPECIFIED — DO NOT INVENT" in final["prompt_text"]
        assert read(ctx)["revision"] == before["revision"]
        with restart(ctx, engine):
            assert current(ctx).json()["final_prompt"] == final
        changed = correct(ctx, read(ctx), next_change)
        assert current(ctx).status_code == 409
        _, completed = command(ctx, changed)
        assert completed.status_code == 200, completed.json()
        updated = completed.json()["final_prompt"]
        assert updated["content_hash"] != final["content_hash"]
        assert updated["prompt_text"] != final["prompt_text"]
        assert updated["assumptions"] == []
        assert 'metal.color: "white"' in updated["prompt_text"]
        assert ctx.provider.calls == []


def test_no_default_policy_does_not_discharge_material_conflict(engine, tmp_path, preprod_enabled):
    with f04_session(engine, tmp_path, binding=True) as ctx:
        initial(ctx, "F", "A gold or platinum ring with an oval diamond center stone.")
        before = read(ctx)
        _, no = command(ctx, before)
        assert no.status_code == 409, no.json()
        assert read(ctx)["revision"] == before["revision"]
        assert current(ctx).json()["status"] == "AWAITING_COMPLETION"
        assert ctx.provider.calls == []
