"""Internal candidate tests, synthetic typed F05 frames; not activation evidence."""

from uuid import UUID

import pytest
import test_final_prompt as f
from jewelai_domain.preservation import contract_hash
from jewelai_domain.smart_defaults_candidate import DefaultPolicyRule
from test_f06_description import as_current_snapshot

from jewelai_prompts import enrich_prompt
from jewelai_prompts.completion_candidate import (
    CompletionIntentCandidate,
    CompletionPolicyCandidate,
    CompletionReviewCandidate,
    prepare_completion_candidate,
)
from jewelai_prompts.enrichment import StructuredPromptEnrichmentResult

ring, templates, runtime, dictionary = f.ring, f.templates, f.runtime, f.dictionary


def verified(revision, templates, runtime):
    result = enrich_prompt(revision, templates, runtime)
    body = result.model_dump(mode="json", exclude={"content_hash"})
    body["knowledge_validation_report_sha256"] = f.REPORT_HASH
    return StructuredPromptEnrichmentResult(**body, content_hash=f._hash(body))


@pytest.fixture
def current(ring, templates, runtime):
    return as_current_snapshot(f._snapshot(ring, verified(ring, templates, runtime)))


def intent(current, choice="NO", **changes):
    payload = dict(
        schema_version="completion-intent-candidate/1.0.0",
        request_id=UUID(int=81),
        message_id=UUID(int=82),
        scope=current.protection_projection.scope,
        expected_frame=current.current_frame,
        anything_else=choice,
        recorded_at=current.revision.created_at,
    )
    payload.update(changes)
    return CompletionIntentCandidate(
        **payload, content_hash=contract_hash("jewelai.CompletionIntentCandidate/1.0.0", payload)
    )


def policy(*rules):
    return CompletionPolicyCandidate(
        schema_version="completion-policy-candidate/1.0.0",
        policy_id="test_only",
        policy_version="1.0.0",
        rules=rules,
    )


def rule(target="metal.finish", value="polished", kind="ring"):
    return DefaultPolicyRule(
        target_path=target,
        proposed_value=value,
        when_jewelry_type=kind,
        rule_id="test_only_finish",
        rule_version="1.0.0",
        rationale="TEST ONLY; no approved professional default asserted.",
    )


def run(current, templates, dictionary, *rules, choice="NO", request=None, version="4.0.0"):
    return prepare_completion_candidate(
        current,
        request or intent(current, choice),
        policy(*rules),
        dictionary=dictionary,
        templates=templates,
        output_version=version,
    )


@pytest.mark.parametrize("version", ["4.0.0", "5.0.0"])
def test_ready_current_output_needs_explicit_no(current, templates, dictionary, version):
    before = current.model_dump_json()
    editing = run(current, templates, dictionary, choice="YES", version=version)
    assert editing.status == "EDITING" and editing.final_prompt is None
    result = run(current, templates, dictionary, version=version)
    assert result.status == "FINAL_AVAILABLE"
    from jewelai_prompts.final_prompt_v4 import assemble_internal_final_prompt_v4
    from jewelai_prompts.final_prompt_v5 import assemble_internal_final_prompt_v5

    builder = (
        assemble_internal_final_prompt_v4
        if version == "4.0.0"
        else assemble_internal_final_prompt_v5
    )
    unchanged = builder(current, dictionary=dictionary, templates=templates).internal_final_prompt
    assert result.final_prompt.model_dump_json() == unchanged.model_dump_json()
    assert result.final_prompt.schema_version == version
    assert result.final_prompt.current_frame == current.current_frame
    assert result == run(current, templates, dictionary, version=version)
    assert CompletionReviewCandidate.model_validate_json(result.model_dump_json()) == result
    assert current.model_dump_json() == before


def test_defaults_are_typed_assumptions_not_relabelled_ifp(current, templates, dictionary):
    result = run(current, templates, dictionary, rule())
    assert result.status == "CONTRACT_APPROVAL_REQUIRED" and result.final_prompt is None
    assert len(result.defaults) == 1
    entry = next(
        x
        for x in result.review_compilation.specification_entries
        if x.concrete_target == "metal.finish"
    )
    assert entry.origin == "assumed" and not entry.confirmed and not entry.locked
    assert result.defaults[0].basis_revision_id == str(current.revision.revision_id)
    assert "test_only_finish" in result.review_compilation.prompt_text
    assert (
        current.revision.design.metal.finish is None
        or current.revision.design.metal.finish.value is None
    )


def test_latest_user_value_supersedes_default_and_old_text(ring, templates, runtime, dictionary):
    first = as_current_snapshot(f._snapshot(ring, verified(ring, templates, runtime)))
    old = run(first, templates, dictionary, rule())

    def update(design):
        design["metal"]["material"]["value"] = "platinum"
        design["metal"]["finish"] = dict(
            availability="value",
            origin="explicit",
            value="matte",
            source=ring.event.source.model_dump(mode="json"),
            confirmed=True,
            locked=False,
        )

    revision = f._changed(ring, update)
    new = as_current_snapshot(f._snapshot(revision, verified(revision, templates, runtime)))
    with pytest.raises(ValueError, match="Stale completion"):
        run(new, templates, dictionary, rule(), request=intent(first))
    result = run(new, templates, dictionary, rule())
    assert not result.defaults
    facts = {x.target: x.value for x in result.final_prompt.design_facts}
    assert facts["metal.material"] == "platinum" and facts["metal.finish"] == "matte"
    assert "polished" not in result.final_prompt.prompt_text
    assert old.defaults and old.intent.expected_frame != result.intent.expected_frame


def test_no_never_discharges_existing_blocked_readiness(ring, templates, runtime, dictionary):
    current = as_current_snapshot(
        f._snapshot(ring, verified(ring, templates, runtime), rule_decision=f._blocked())
    )
    result = run(current, templates, dictionary)
    assert result.status == "CONTRACT_APPROVAL_REQUIRED" and result.final_prompt is None


def test_scope_frame_policy_and_intent_integrity(current, templates, dictionary):
    bad = intent(current).model_dump(mode="json")
    bad["anything_else"] = "YES"
    with pytest.raises(ValueError, match="integrity"):
        CompletionIntentCandidate.model_validate(bad)
    scope = current.protection_projection.scope.model_copy(update={"organization_id": UUID(int=99)})
    with pytest.raises(ValueError, match="scope mismatch"):
        run(current, templates, dictionary, request=intent(current, scope=scope))
    frame = current.current_frame.model_copy(update={"history_root_sha256": "0" * 64})
    with pytest.raises(ValueError, match="Stale completion"):
        run(current, templates, dictionary, request=intent(current, expected_frame=frame))
    with pytest.raises(ValueError):
        run(current, templates, dictionary, rule(value={"unsupported": "shape"}))
    with pytest.raises(ValueError, match="Unsupported completion"):
        run(current, templates, dictionary, version="6.0.0")


def test_pending_keep_consent_blocks_every_completion(current, templates, dictionary):
    p = current.protection_projection.model_dump(mode="json", exclude={"content_hash"})
    p["pending_requests"] = [dict(intent_id="1" * 64, current_offer_ref=None, status="PENDING")]
    p["content_hash"] = contract_hash("jewelai.ProtectionProjection/1.0.0", p)
    current = type(current).model_validate({**current.model_dump(), "protection_projection": p})
    result = run(current, templates, dictionary, rule())
    assert result.status == "PROTECTION_BLOCKED"
    assert not result.defaults and result.final_prompt is None
