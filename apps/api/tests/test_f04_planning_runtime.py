"""F profile tests reuse actual source parsing/Matrix/planning and native fixtures."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from jewelai_domain.clarification_state import EvidenceScope
from jewelai_domain.models import DesignRevision, MessageSource
from jewelai_domain.revisions import revise_design
from jewelai_parser import parse_full_message
from test_parsed_enrichment import NOW, ROOT
from test_parsed_enrichment import collision_release as collision_release
from test_parsed_enrichment import dictionary as dictionary
from test_parsed_enrichment import ring as ring

from jewelai_api.artifacts import load_runtime_artifacts
from jewelai_api.clarification_v2 import InitialTrigger
from jewelai_api.conflict_evidence import product_body_material_conflict
from jewelai_api.f04_planning import f04_evaluation, input_context, plan_f04
from jewelai_api.parsed_enrichment import (
    enrich_parsed_candidates_with_active_release,
    proposed_design_for_transition,
)
from jewelai_api.settings import ArtifactVersions


@pytest.mark.parametrize(
    "text,kind",
    [
        ("Gold or platinum ring with an oval diamond.", "alternative"),
        ("Gold and platinum ring.", "competing"),
        ("A gold ring with gold metal.", "equivalent"),
    ],
)
def test_f04_real_parsing_to_plan(text, kind, ring, collision_release):
    artifacts = load_runtime_artifacts(ROOT, ArtifactVersions(questions="2.0.0", rules="2.0.0"))
    data = ring.model_dump(mode="json")
    data["design"] = {}
    revision = DesignRevision.model_validate(data)
    store, stored, compiled, report, active = collision_release
    scope = EvidenceScope(organization_id=uuid4(), session_id=uuid4(), design_id=revision.design_id)
    cycle, plan, message = uuid4(), uuid4(), uuid4()
    pin = SimpleNamespace(
        package_id=stored.package_id,
        artifact_version=stored.artifact_version,
        runtime_sha256=active.runtime_sha256,
        validation_report_sha256=active.validation_report_sha256,
    )
    ctx = input_context(scope, revision, cycle, 1, artifacts, pin)
    source = MessageSource(message_id=str(message), recorded_at=NOW)
    parsed = parse_full_message(
        text, locale="en", dictionary=artifacts.dictionary, knowledge_runtime=compiled
    )
    conflict = product_body_material_conflict(
        parsed,
        message=SimpleNamespace(
            message_id=message, session_id=scope.session_id, actor="user", content=text
        ),
        context=ctx,
        dictionary=artifacts.dictionary,
        knowledge_runtime=compiled,
    )
    assert conflict and conflict.kind == kind

    def evaluate(rev):
        return enrich_parsed_candidates_with_active_release(
            rev,
            parse_result=parsed,
            source=source,
            dictionary=artifacts.dictionary,
            templates=artifacts.prompts,
            artifact_store=store,
            knowledge_package_id=stored.package_id,
            knowledge_artifact_version=stored.artifact_version,
            active_release=active,
            validation_report=report,
            equivalent_candidate_ids=tuple(o.candidate_id for o in conflict.occurrences)
            if kind == "equivalent"
            else (),
        )

    initial = evaluate(revision)
    proposed = proposed_design_for_transition(revision, initial)
    authoritative = (
        revise_design(
            revision,
            proposed,
            expected_revision_id=revision.revision_id,
            source=source,
            reason="Synthetic explicit F source",
            created_at=NOW,
        )
        if proposed != revision.design
        else revision
    )
    result = f04_evaluation(evaluate(authoritative), revision=authoritative, context=ctx)
    actual = plan_f04(
        authoritative,
        result,
        artifacts=artifacts,
        role_id="retail_client",
        plan_id=plan,
        cycle_id=cycle,
        cycle_number=1,
        trigger=InitialTrigger(kind="initial", message_id=message),
        conflicts=(conflict,),
    )
    assert actual.plan_version == "2.0.0"
    material = [q for q in actual.questions if q.semantic_question_id == "METAL_MATERIAL"]
    if kind == "equivalent":
        assert authoritative.design.metal.material.value == "gold" and not material
    else:
        assert authoritative.design.metal.material is None
        assert len(material) == 1 and tuple(o.value for o in material[0].options) == (
            "gold",
            "platinum",
        )
        assert (
            material[0].text == "Which metal would you like for the product body: gold or platinum?"
        )

    from jewelai_prompts.final_prompt import FinalPromptArtifactVersions, KnowledgeReleaseReference
    from jewelai_prompts.final_prompt_v3 import (
        FinalPromptSnapshotV2,
        assemble_internal_final_prompt_v3,
    )
    from jewelai_prompts.handoff import build_internal_final_prompt_handoff

    from jewelai_api.clarification_v2 import seal_frontier

    snapshot = FinalPromptSnapshotV2(
        schema_version="2.0.0",
        contract_profile=ctx.contract_profile,
        session_id=scope.session_id,
        organization_id=scope.organization_id,
        locale="en",
        revision=authoritative,
        enrichment_cycle_id=cycle,
        latest_enrichment_cycle_id=cycle,
        enrichment_cycle_number=1,
        enrichment_result=result.enrichment_result,
        knowledge_release=KnowledgeReleaseReference(**vars(pin)),
        artifact_versions=FinalPromptArtifactVersions(
            design_schema_version=revision.schema_version,
            dictionary_artifact_version="1.0.0",
            question_artifact_version="2.0.0",
            rules_artifact_version="2.0.0",
            prompt_template_artifact_version="1.0.0",
            enrichment_version="2.0.0",
        ),
        rule_decision=actual.rule_decision,
        effective_unresolved_frontier=seal_frontier(actual, (actual,)),
        cause_definitions=actual.cause_definitions,
    )
    assembly = assemble_internal_final_prompt_v3(
        snapshot, dictionary=artifacts.dictionary, templates=artifacts.prompts
    )
    assert assembly.internal_final_prompt.schema_version == "3.0.0"
    assert assembly.description.schema_version == "2.0.0"
    handoff = build_internal_final_prompt_handoff(assembly)
    assert (
        handoff.schema_version == "3.0.0"
        and handoff.internal_final_prompt_schema_version == "3.0.0"
    )
