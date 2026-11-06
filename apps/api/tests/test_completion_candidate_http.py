"""Persisted HTTP -> verified snapshot -> unregistered completion prototype.

Fake authentication/Knowledge bindings; no completion rows/routes are created.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from jewelai_domain.preservation import contract_hash
from jewelai_prompts.completion_candidate import (
    CompletionIntentCandidate,
    CompletionPolicyCandidate,
    prepare_completion_candidate,
)
from test_conversation import correct, read
from test_f04_http import f04_session, restart
from test_f05_history import initial

from jewelai_api import continuation_preview


def test_current_http_corrections_restart_and_stale_completion(engine, tmp_path, monkeypatch):
    captured = {}
    original = continuation_preview.assemble_internal_final_prompt_v4

    def capture(snapshot, **kwargs):
        result = original(snapshot, **kwargs)
        captured.update(snapshot=snapshot, kwargs=kwargs)
        return result

    monkeypatch.setattr(continuation_preview, "assemble_internal_final_prompt_v4", capture)
    with f04_session(engine, tmp_path, binding=True) as ctx:
        initial(ctx, "F")
        before = read(ctx)
        old_frame = captured["snapshot"].current_frame
        for wording in ("Change the metal to platinum.", "Use yellow gold.", "Use platinum."):
            before = correct(ctx, before, wording)
        snapshot = captured["snapshot"]
        assert snapshot.revision.design.metal.material.value == "platinum"
        payload = dict(
            schema_version="completion-intent-candidate/1.0.0",
            request_id=uuid4(),
            message_id=uuid4(),
            scope=snapshot.protection_projection.scope,
            expected_frame=snapshot.current_frame,
            anything_else="NO",
            recorded_at=datetime(2026, 11, 6, tzinfo=UTC),
        )
        request = CompletionIntentCandidate(
            **payload,
            content_hash=contract_hash("jewelai.CompletionIntentCandidate/1.0.0", payload),
        )
        policy = CompletionPolicyCandidate(
            schema_version="completion-policy-candidate/1.0.0",
            policy_id="test_empty",
            policy_version="1.0.0",
            rules=(),
        )

        def complete():
            return prepare_completion_candidate(
                captured["snapshot"],
                request,
                policy,
                dictionary=ctx.runtime.artifacts.dictionary,
                templates=ctx.runtime.artifacts.prompts,
                _source_facts=captured["kwargs"]["_source_facts"],
                _pending_descriptions=captured["kwargs"]["_pending_descriptions"],
            )

        result = complete()
        assert result.status == "FINAL_AVAILABLE"
        verified = original(captured["snapshot"], **captured["kwargs"])
        assert result.final_prompt == verified.internal_final_prompt
        assert result.final_prompt.current_frame == snapshot.current_frame
        facts = {f.target: f.value for f in result.final_prompt.design_facts}
        assert facts["metal.material"] == "platinum"
        assert snapshot.protection_projection.roots  # Original KEEP remains active.
        assert read(ctx) == before
        with restart(ctx, engine):
            assert read(ctx) == before
            assert complete() == result
        stale = {**payload, "expected_frame": old_frame}
        old = CompletionIntentCandidate(
            **stale, content_hash=contract_hash("jewelai.CompletionIntentCandidate/1.0.0", stale)
        )
        with pytest.raises(ValueError, match="Stale completion"):
            prepare_completion_candidate(
                captured["snapshot"],
                old,
                policy,
                dictionary=ctx.runtime.artifacts.dictionary,
                templates=ctx.runtime.artifacts.prompts,
            )
        assert read(ctx) == before
