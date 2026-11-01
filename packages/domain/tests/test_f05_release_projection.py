"""Pure release evidence tests; not an HTTP authorization or persistence proof."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_f05_preservation import revision, root

from jewelai_domain.clarification_state import EvidenceScope, evidence_hash
from jewelai_domain.continuation import (
    ContinuationArtifactPins,
    ContinuationContext,
    ContinuationFrame,
)
from jewelai_domain.models import DesignRevision, Explicit, MessageSource
from jewelai_domain.preservation import (
    PendingPreservationRequest,
    PreservationConflict,
    PreservationRootReference,
    anchor_hash,
    build_preservation_root,
    center_target_ref,
    contract_hash,
    initial_protection_projection,
)
from jewelai_domain.preservation_release import (
    KeepReleaseDecision,
    KeepReleaseIntent,
    KeepReleaseOffer,
    KeepReofferBinding,
    anchor_set_hash,
    project_unprotected_transition,
    project_verified_release,
    requested_value_hash,
)
from jewelai_domain.revisions import revise_design


def seal(cls, name, payload, identity=None):
    if identity:
        payload = {**payload, identity: contract_hash(f"jewelai.{name}/1.0.0", payload)}
    return cls(**payload, content_hash=contract_hash(f"jewelai.{name}/1.0.0", payload))


def release_fixture(
    *,
    decision="ACCEPT",
    bad_anchor=False,
    requested="emerald_cut",
    schema="1.1.0",
    base="L",
    previous=None,
):
    before = revision()
    if schema == "1.0.0":
        before = DesignRevision(
            schema_version="1.0.0",
            design_id=before.design_id,
            revision_id=before.revision_id,
            revision=1,
            created_at=before.created_at,
            parent_revision_id=None,
            event=before.event,
            design={"center_stone": {"shape": before.design.center_stone.shape}},
        )
    roots = (
        root(before),
        build_preservation_root(
            evidence_id="constraint_" + "c" * 24,
            evidence_hash="d" * 64,
            source_revision=before,
            source_cycle_id=uuid4(),
            field="shape",
        ),
    )
    scope = EvidenceScope(session_id=uuid4(), organization_id=uuid4(), design_id=before.design_id)
    protection = initial_protection_projection(before, scope, roots)
    context = ContinuationContext(
        scope=scope,
        retained_base=base,
        extension_profile="jewelai.prompt-enrichment.f05/1.0.0",
        parser_interpreter_id="f05-1.2",
        release_pin=dict(
            package_id="synthetic",
            artifact_version="1.0.0",
            runtime_sha256="a" * 64,
            validation_report_sha256="b" * 64,
        ),
        artifact_pins=ContinuationArtifactPins(
            design_schema_version=before.schema_version,
            role_artifact_version="1.0.0",
            dictionary_artifact_version="1.0.0",
            question_schema_version="1.0.0" if base == "L" else "2.0.0",
            question_artifact_version="1.0.0" if base == "L" else "2.0.0",
            rules_schema_version="1.0.0" if base == "L" else "2.0.0",
            rules_artifact_version="1.0.0" if base == "L" else "2.0.0",
            prompt_template_artifact_version="1.0.0",
            dictionary_sha256="a" * 64,
            question_sha256="b" * 64,
            rules_sha256="c" * 64,
        ),
    )
    if previous is not None:
        before = previous.after
        roots = previous.roots
        protection = project(previous)
        context = previous.intent.context
    head = ContinuationFrame(
        revision_id=before.revision_id,
        revision_sha256=evidence_hash(before),
        enrichment_cycle_id=uuid4(),
        enrichment_cycle_number=2
        if previous is None
        else previous.current_head.enrichment_cycle_number + 1,
        enrichment_result_hash="a" * 64,
        plan_id=uuid4(),
        plan_hash="b" * 64,
        history_root_sha256="c" * 64,
    )
    origin = head.model_copy(
        update={"plan_id": uuid4(), "enrichment_cycle_number": head.enrichment_cycle_number - 1}
    )
    source = MessageSource(message_id=str(uuid4()), recorded_at=before.created_at)
    state = Explicit(value=requested, source=source)
    target = center_target_ref("center_stone.shape")
    root_refs = tuple(
        PreservationRootReference(
            evidence_id=r.evidence_id,
            content_hash=r.evidence_hash,
            source_revision_id=r.source_revision_id,
            source_cycle_id=r.source_cycle_id,
        )
        for r in roots
    )
    intent = seal(
        KeepReleaseIntent,
        "KeepReleaseIntent",
        dict(
            schema_version="1.0.0",
            context=context,
            origin_head=origin,
            correction_record_id=uuid4(),
            source=source,
            message_sha256="d" * 64,
            parse_version="1.2.0",
            parse_hash="e" * 64,
            proposal_hash="f" * 64,
            source_candidate_ids=("candidate_1",),
            source_spans=(dict(start=0, end=10, text_sha256="e" * 64),),
            target=target,
            original_before_state=before.design.center_stone.shape,
            requested_state=state,
            requested_value_sha256=requested_value_hash(requested),
            keep_roots=root_refs,
        ),
        "intent_id",
    )
    binding = seal(
        KeepReofferBinding,
        "ReofferBinding",
        dict(
            schema_version="1.0.0",
            intent_id=intent.intent_id,
            previous_offer_ref=None,
            previous_binding_ref=None,
            owning_plan_id=head.plan_id,
            source_head=origin,
            current_before_state_sha256=anchor_hash(before.design.center_stone.shape),
            anchor_set_sha256="0" * 64 if bad_anchor else anchor_set_hash(protection),
            applicable_keep_roots=root_refs,
            allowed_decisions=("ACCEPT", "REJECT"),
        ),
        "binding_id",
    )
    offer = seal(
        KeepReleaseOffer,
        "Offer",
        dict(
            schema_version="1.0.0",
            intent_id=intent.intent_id,
            binding=binding,
            target=target,
            requested_value_sha256=intent.requested_value_sha256,
            locale="en",
            rendered_question="Synthetic source-bound release offer.",
            allowed_decisions=binding.allowed_decisions,
            owning_plan_id=head.plan_id,
        ),
        "offer_id",
    )
    pending = (
        PendingPreservationRequest(
            intent_id=intent.intent_id,
            current_offer_ref=dict(id=offer.offer_id, hash=offer.content_hash),
            status="PENDING",
        ),
        PendingPreservationRequest(
            intent_id="f" * 64, current_offer_ref=None, status="RECONFIRMATION_REQUIRED"
        ),
    )
    protection = seal(
        type(protection),
        "ProtectionProjection",
        {
            **protection.model_dump(exclude={"content_hash"}),
            "pending_requests": pending,
        },
    )
    authority = MessageSource(message_id=str(uuid4()), recorded_at=before.created_at)
    if decision == "ACCEPT":
        design = before.design.model_dump(mode="json")
        design["center_stone"]["shape"] = state.model_dump(mode="json")
        after = revise_design(
            before,
            design,
            expected_revision_id=before.revision_id,
            source=authority,
            reason="Synthetic typed scoped release",
            created_at=before.created_at,
        )
    else:
        after = before
    decided = seal(
        KeepReleaseDecision,
        "KeepReleaseDecision",
        dict(
            schema_version="1.0.0",
            decision_id=uuid4(),
            request_hash="c" * 64,
            context=context,
            intent_id=intent.intent_id,
            offer_id=offer.offer_id,
            binding_hash=binding.content_hash,
            previous_head=head,
            decision=decision,
            source=authority,
            message_sha256="d" * 64,
            outcome="APPLIED" if decision == "ACCEPT" else "REJECTED",
            resulting_revision_id=after.revision_id if decision == "ACCEPT" else None,
            accepted_target=dict(
                target=target,
                before_state_sha256=anchor_hash(before.design.center_stone.shape),
                after_state_sha256=anchor_hash(after.design.center_stone.shape),
            )
            if decision == "ACCEPT"
            else None,
        ),
    )
    return SimpleNamespace(
        before=before,
        after=after,
        roots=roots,
        protection=protection,
        intent=intent,
        offer=offer,
        decision=decided,
        current_head=head,
    )


def project(fixture, **changes):
    return project_verified_release(**{**vars(fixture), **changes})


@pytest.mark.parametrize("schema", ["1.0.0", "1.1.0"])
@pytest.mark.parametrize("base", ["L", "F"])
def test_accept_reanchors_all_overlapping_roots_and_preserves_other_wrappers_and_sources(
    schema, base
):
    f = release_fixture(schema=schema, base=base)
    original = tuple(r.model_dump_json() for r in f.roots)
    prior = f.protection.model_dump_json()
    result = project(f)
    changed = [a for a in result.anchors if a.target.concrete_target == "center_stone.shape"]
    assert len(changed) == 2
    assert all(
        a.baseline_state_sha256 == anchor_hash(f.after.design.center_stone.shape) for a in changed
    )
    assert all(a.last_accepted_release_ref.id == f.decision.decision_id for a in changed)
    before_other = [
        a for a in f.protection.anchors if a.target.concrete_target != "center_stone.shape"
    ]
    assert [
        a for a in result.anchors if a.target.concrete_target != "center_stone.shape"
    ] == before_other
    assert f.after.design.center_stone.shape.source == f.intent.source
    assert f.after.event.source == f.decision.source
    assert len(result.pending_requests) == 1 and result.pending_requests[0].intent_id == "f" * 64
    assert f.protection.model_dump_json() == prior
    assert tuple(r.model_dump_json() for r in f.roots) == original
    assert project(f) == result


def test_reject_closes_only_its_pending_request_without_reanchoring():
    f = release_fixture(decision="REJECT")
    result = project(f)
    assert result.anchors == f.protection.anchors
    assert result.current_revision_id == f.before.revision_id
    assert not result.applied_decision_refs and len(result.pending_requests) == 1


@pytest.mark.parametrize("violation", ["head", "roots", "anchors", "already_current"])
def test_rehashed_or_stale_release_context_cannot_authorize_a_change(violation):
    f = release_fixture(
        bad_anchor=violation == "anchors",
        requested="oval" if violation == "already_current" else "emerald_cut",
    )
    changes = {}
    if violation == "head":
        changes["current_head"] = f.current_head.model_copy(update={"plan_hash": "0" * 64})
    if violation == "roots":
        changes["roots"] = f.roots[:1]
    with pytest.raises(PreservationConflict):
        project(f, **changes)


def test_anchor_set_excludes_pending_offers_but_includes_actual_anchors():
    f = release_fixture()
    without_pending = seal(
        type(f.protection),
        "ProtectionProjection",
        {
            **f.protection.model_dump(exclude={"content_hash"}),
            "pending_requests": (),
        },
    )
    assert anchor_set_hash(without_pending) == anchor_set_hash(f.protection)
    assert anchor_set_hash(project(f)) != anchor_set_hash(f.protection)


def test_unrelated_edit_preserves_all_anchors_and_requires_explicit_reoffer():
    f = release_fixture()
    design = f.before.design.model_dump(mode="json")
    source = MessageSource(message_id=str(uuid4()), recorded_at=f.before.created_at)
    design["metal"]["material"] = Explicit(value="platinum", source=source).model_dump(mode="json")
    after = revise_design(
        f.before,
        design,
        expected_revision_id=f.before.revision_id,
        source=source,
        reason="Independent synthetic body-metal edit",
        created_at=f.before.created_at,
    )
    current = project_unprotected_transition(before=f.before, after=after, protection=f.protection)
    assert current.anchors == f.protection.anchors
    assert current.roots == f.protection.roots
    assert {p.intent_id for p in current.pending_requests} == {
        p.intent_id for p in f.protection.pending_requests
    }
    assert all(
        p.current_offer_ref is None and p.status == "RECONFIRMATION_REQUIRED"
        for p in current.pending_requests
    )
    with pytest.raises(PreservationConflict):
        project_unprotected_transition(before=f.before, after=f.after, protection=f.protection)


def test_later_different_value_requires_fresh_value_bound_release():
    first = release_fixture()
    first_current = project(first)
    second = release_fixture(previous=first, requested="round")
    with pytest.raises(PreservationConflict):
        project(second, decision=first.decision)
    second_current = project(second)
    assert len(second_current.applied_decision_refs) == 2
    assert second.intent.intent_id != first.intent.intent_id
    assert second.intent.requested_value_sha256 != first.intent.requested_value_sha256
    assert first.after.design.center_stone.shape.value == "emerald_cut"
    assert second.after.design.center_stone.shape.value == "round"
    assert all(
        a.last_accepted_release_ref.id == second.decision.decision_id
        for a in second_current.anchors
        if a.target.concrete_target == "center_stone.shape"
    )
    assert first_current.current_revision_id == first.after.revision_id
