"""The real proposed policy's complete API owning scope; no professional activation."""

import pytest
from conftest import ROOT
from jewelai_prompts.completion import CompletionRegistry
from test_conversation import correct, read
from test_f04_http import f04_session
from test_f05_history import initial
from test_prompt_completion import command
from test_prompt_completion import enabled as enabled

from jewelai_api.completion import load_registry

POLICY = ROOT / "data/completion/proposed-1.0.0.json"


def test_actual_proposed_registry_cannot_activate():
    proposed = CompletionRegistry.model_validate_json(POLICY.read_bytes())
    assert proposed.review_status == "PROPOSED"
    with pytest.raises(ValueError, match="approval"):
        load_registry(POLICY, proposed.sha256)


def test_actual_registry_context_and_latest_state_http(engine, tmp_path, enabled):
    proposed = CompletionRegistry.model_validate_json(POLICY.read_bytes())
    wire = proposed.model_dump(mode="json")
    wire["review_status"] = "APPROVED"  # Isolated TEST ONLY copy, never the actual artifact.
    reviewed = CompletionRegistry.model_validate(wire)
    path = tmp_path / "test-only-approved-policy.json"
    path.write_text(reviewed.model_dump_json())
    reviewed = load_registry(path, reviewed.sha256)
    with f04_session(engine, tmp_path, binding=True) as ctx:
        ctx.app.state.completion_service.registry = reviewed
        initial(
            ctx,
            "F",
            "A white gold ring with an oval diamond center stone in prong setting. "
            "Center stone 8 x 6 x 4 mm.",
        )
        _, completed = command(ctx, read(ctx))
        assert completed.status_code == 200, completed.json()
        prompt = completed.json()["final_prompt"]
        assert prompt["policy_sha256"] == reviewed.sha256
        assert [(p["target_path"], p["proposed_value"]) for p in prompt["assumptions"]] == [
            ("metal.finish", "polished")
        ]
        changed = correct(ctx, read(ctx), "Use platinum.")
        _, completed = command(ctx, changed)
        assert completed.status_code == 200, completed.json()
        assert not completed.json()["final_prompt"]["assumptions"]
        assert proposed.review_status == "PROPOSED"
        assert CompletionRegistry.model_validate_json(POLICY.read_bytes()) == proposed
        assert ctx.provider.calls == []
