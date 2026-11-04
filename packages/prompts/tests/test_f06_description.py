"""F06 privacy/fidelity regressions use existing canonical output fixtures."""

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import test_final_prompt as f
from jewelai_domain.clarification_state import EvidenceScope, evidence_hash
from jewelai_domain.compatibility import CompatibilityReadinessProjection
from jewelai_domain.continuation import ContinuationArtifactPins, ContinuationFrame
from jewelai_domain.models_v1_1 import DesignRevisionV1_1, upgrade_design_revision_v1_to_v1_1
from jewelai_domain.preservation import contract_hash, initial_protection_projection

from jewelai_prompts import enrich_prompt
from jewelai_prompts.enrichment import StructuredPromptEnrichmentResult
from jewelai_prompts.final_prompt import _constraints, _design_facts, _unresolved_details
from jewelai_prompts.final_prompt_v4 import FinalPromptSnapshotV3
from jewelai_prompts.final_prompt_v5 import assemble_internal_final_prompt_v5
from jewelai_prompts.review_description import render_review_description

dictionary = f.dictionary
templates = f.templates
ring = f.ring
runtime = f.runtime


def render(ring, templates, runtime, dictionary, changes, locale):
    payload = upgrade_design_revision_v1_to_v1_1(ring).model_dump(mode="json")
    payload["design"].update(changes)
    revision = DesignRevisionV1_1.model_validate(payload)
    enrichment = enrich_prompt(revision, templates, runtime)
    body = enrichment.model_dump(mode="json", exclude={"content_hash"})
    body["knowledge_validation_report_sha256"] = f.REPORT_HASH
    enrichment = StructuredPromptEnrichmentResult(**body, content_hash=f._hash(body))
    snapshot = f._snapshot(revision, enrichment, locale=locale)
    snapshot = as_current_snapshot(snapshot)
    facts = _design_facts(snapshot)
    description = render_review_description(
        snapshot,
        facts,
        _constraints(snapshot, facts),
        _unresolved_details(snapshot),
        dictionary=dictionary,
    )
    before = snapshot.model_dump_json()
    assembly = assemble_internal_final_prompt_v5(
        snapshot, dictionary=dictionary, templates=templates
    )
    assert before == snapshot.model_dump_json()
    assert assembly.description.text == description.text
    return SimpleNamespace(
        text=description.text, coverage=description.coverage, assembly=assembly, snapshot=snapshot
    )


def as_current_snapshot(snapshot):
    """Synthetic typed L read frame, not runtime authorization or persisted history."""
    scope = EvidenceScope(
        session_id=snapshot.session_id,
        organization_id=snapshot.organization_id,
        design_id=snapshot.revision.design_id,
    )
    frame = ContinuationFrame(
        revision_id=snapshot.revision.revision_id,
        revision_sha256=evidence_hash(snapshot.revision),
        enrichment_cycle_id=snapshot.enrichment_cycle_id,
        enrichment_cycle_number=snapshot.enrichment_cycle_number,
        enrichment_result_hash=snapshot.enrichment_result.content_hash,
        plan_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        plan_hash="1" * 64,
        history_root_sha256="2" * 64,
    )
    pins = ContinuationArtifactPins(
        design_schema_version=snapshot.revision.schema_version,
        role_artifact_version="1.0.0",
        dictionary_artifact_version="1.0.0",
        question_schema_version="1.0.0",
        question_artifact_version="1.0.0",
        rules_schema_version="1.0.0",
        rules_artifact_version="1.0.0",
        prompt_template_artifact_version="1.0.0",
        dictionary_sha256="3" * 64,
        question_sha256="4" * 64,
        rules_sha256="5" * 64,
    )
    compat = dict(
        schema_version="1.0.0",
        projection_id="jewelai.legacy-l.compat/1.0.0",
        scope=scope,
        build_mode="read_only_output",
        current_frame_core=frame.model_dump(exclude={"plan_hash", "history_root_sha256"}),
        evidence_head=frame,
        retained_artifact_pins=pins,
        legacy_history_root_sha256=frame.history_root_sha256,
        proofs=(),
        remaining_blocker_refs=(),
    )
    compat = CompatibilityReadinessProjection(
        **compat,
        content_hash=contract_hash("jewelai.CompatibilityReadinessProjection/1.0.0", compat),
    )
    return FinalPromptSnapshotV3(
        **snapshot.model_dump(),
        schema_version="3.0.0",
        retained_base="L",
        extension_profile=None,
        current_frame=frame,
        protection_projection=initial_protection_projection(snapshot.revision, scope, ()),
        compatibility_projection=compat,
        native_frontier=None,
        cause_definitions=(),
    )


def explicit(ring, value):
    return dict(
        availability="value",
        origin="explicit",
        value=value,
        confirmed=True,
        locked=False,
        source=ring.event.source.model_dump(mode="json"),
    )


@pytest.mark.parametrize("locale", ["en", "ru"])
def test_f06_present_style_and_prongs_are_visible(ring, templates, runtime, dictionary, locale):
    description = render(
        ring,
        templates,
        runtime,
        dictionary,
        dict(style_influences=explicit(ring, ["geometric"]), prong_count=explicit(ring, 4)),
        locale,
    )
    assert "geometric" in description.text
    assert "4" in description.text


@pytest.mark.parametrize("locale", ["en", "ru"])
def test_f06_components_never_dump_metadata(ring, templates, runtime, dictionary, locale):
    description = render(
        ring,
        templates,
        runtime,
        dictionary,
        dict(
            metal={
                "components": explicit(
                    ring,
                    [
                        {
                            "component_id": "internal_head_k7",
                            "role_or_location": explicit(ring, "head"),
                            "material": explicit(ring, "platinum"),
                        },
                        {
                            "component_id": "internal_shank_z9",
                            "role_or_location": explicit(ring, "shank"),
                            "material": explicit(ring, "gold"),
                        },
                    ],
                )
            }
        ),
        locale,
    )
    assert "internal_head_k7" not in description.text
    assert '"availability"' not in description.text
    assert "example-request" not in description.text
    assert (
        "Metal component 1 — Head: Material: platinum"
        if locale == "en"
        else "Компонент металла 1 — Головка: Материал: платина"
    ) in description.text
    assert (
        "Metal component 2 — Shank: Material: gold"
        if locale == "en"
        else "Компонент металла 2 — Шинка: Материал: золото"
    ) in description.text


@pytest.mark.parametrize("locale", ["en", "ru"])
def test_rich_style_negative_features_and_construction(
    ring, templates, runtime, dictionary, locale
):
    result = render(
        ring,
        templates,
        runtime,
        dictionary,
        dict(
            style_descriptors=explicit(ring, ["minimalist"]),
            style_influences=explicit(ring, ["geometric"]),
            style_period_or_movement=explicit(ring, "art_deco"),
            prong_configuration=explicit(ring, "four_prong"),
            halo={"enabled": explicit(ring, False)},
            pave={"enabled": explicit(ring, False)},
            construction={
                "shank": explicit(ring, "tapered"),
                "ring": {"inner_diameter_mm": explicit(ring, {"value": 17, "unit": "mm"})},
            },
        ),
        locale,
    )
    text = result.text
    for value in ("geometric", "art_deco", "four_prong", "17"):
        assert value in text
    assert ("minimalist" if locale == "en" else "минимализм") in text
    assert ("Halo / Enabled: absent" if locale == "en" else "Гало / Наличие: нет") in text
    assert ("Pavé / Enabled: absent" if locale == "en" else "Паве / Наличие: нет") in text
    facts = result.assembly.internal_final_prompt.design_facts
    assert next(f for f in facts if f.target == "halo.enabled").value is False
    assert {c.target for c in result.coverage if c.kind == "fact"} == {f.target for f in facts}
    assert len(result.coverage) == len(facts) + len(
        result.assembly.internal_final_prompt.constraints
    )
    assert not any("coverage" in key for key in result.assembly.model_dump())


@pytest.mark.parametrize("locale", ["en", "ru"])
def test_side_group_dimensions_and_quantity_keep_ownership(
    ring, templates, runtime, dictionary, locale
):
    # Existing ring fixture has a real supported side-stone group, no new group inference.
    result = render(ring, templates, runtime, dictionary, {}, locale)
    source_facts = result.assembly.internal_final_prompt.design_facts
    side = [f for f in source_facts if f.target.startswith("side_stones.")]
    assert side
    for fact in side:
        entry = next(c for c in result.coverage if c.kind == "fact" and c.target == fact.target)
        assert entry.owner == ".".join(fact.target.split(".")[:2])
    assert ("Side-stone group 1" if locale == "en" else "Группа боковых камней 1") in result.text
    assert ("per side" if locale == "en" else "с каждой стороны") in result.text
    assert "shoulder-pair" not in result.text


@pytest.mark.parametrize("locale", ["en", "ru"])
def test_authority_keep_lock_and_unresolved_are_distinct(
    ring, templates, runtime, dictionary, locale
):
    from jewelai_domain.knowledge_policy import RuntimeProvenance

    from jewelai_prompts.final_prompt import FinalPromptConstraint, FinalPromptUnresolvedDetail

    result = render(ring, templates, runtime, dictionary, {}, locale)
    fact = result.assembly.internal_final_prompt.design_facts[0]
    facts = tuple(
        fact.model_copy(
            update=dict(
                target=target,
                origin=origin,
                confirmed=confirmed,
                locked=locked,
                provenance=provenance,
            )
        )
        for target, origin, confirmed, locked, provenance in (
            ("center_stone.shape", "explicit", True, True, RuntimeProvenance.USER_CONFIRMED),
            ("metal.material", "explicit", False, False, RuntimeProvenance.USER_EXPLICIT_LATEST),
            ("style", "assumed", False, False, RuntimeProvenance.VISUALIZATION_ASSUMPTION),
            (
                "style_influences",
                "derived",
                True,
                False,
                RuntimeProvenance.USER_ACCEPTED_RECOMMENDATION,
            ),
        )
    )
    keep = FinalPromptConstraint(
        kind="preservation",
        target="component.center_stone",
        instruction="Keep the current center stone unchanged.",
    )
    unknown = FinalPromptUnresolvedDetail(
        target="center_stone.dimensions", classification="unknown", blocking=True
    )
    rendered = render_review_description(
        result.snapshot, facts, (keep,), (unknown,), dictionary=dictionary
    )
    for word in (
        ("User-confirmed", "Unconfirmed", "Assumption", "Accepted recommendation", "unknown")
        if locale == "en"
        else (
            "Подтверждено пользователем",
            "Не подтверждено",
            "Предположение",
            "Принятая рекомендация",
            "неизвестно",
        )
    ):
        assert word in rendered.text
    assert "LOCK" in rendered.text and "KEEP" in rendered.text
    assert len(rendered.coverage) == 5


@pytest.mark.parametrize("locale", ["en", "ru"])
@pytest.mark.parametrize(
    "target,value,reason",
    [
        ("style", "https://private.invalid/image?token=secret", "private_or_opaque_value"),
        ("style", "gs://private.invalid/image", "private_or_opaque_value"),
        ("style", "a8c58751-3112-40a5-808a-638d8bb76b50", "private_or_opaque_value"),
        ("style", {"source": {"message_id": "private-source"}}, "unsupported_label"),
        ("not_an_approved_label", 7, "unsupported_label"),
        ("style", "an_untranslated_term", "untranslated_source_term"),
        ("style", {}, "unsupported_value_type"),
    ],
)
def test_unsupported_is_explicit_not_a_json_fallback(
    ring, templates, runtime, dictionary, locale, target, value, reason
):
    result = render(ring, templates, runtime, dictionary, {}, locale)
    fact = result.assembly.internal_final_prompt.design_facts[0].model_copy(
        update=dict(target=target, value=value)
    )
    rendered = render_review_description(result.snapshot, (fact,), (), (), dictionary=dictionary)
    assert rendered.coverage[0].status == "unsupported"
    assert rendered.coverage[0].reason.value == reason
    assert "private.invalid" not in rendered.text and "message_id" not in rendered.text
    assert "a8c58751" not in rendered.text
    assert "{" not in rendered.text and "}" not in rendered.text


def test_new_families_roundtrip_hashes_reject_tampering_and_downstream(
    ring, templates, runtime, dictionary
):
    from copy import deepcopy

    from pydantic import ValidationError

    from jewelai_prompts.downstream_preparation import (
        GenerationPreparationError,
        build_generation_preparation,
    )
    from jewelai_prompts.downstream_preparation_v2 import build_generation_preparation_v2
    from jewelai_prompts.final_prompt_v5 import (
        CanonicalFinalPromptAssemblyV5,
        CanonicalInternalFinalPromptHandoffV5,
    )
    from jewelai_prompts.handoff import build_internal_final_prompt_handoff

    result = render(ring, templates, runtime, dictionary, {}, "en")
    output = result.assembly
    assert output.description.schema_version == "4.0.0"
    assert output.internal_final_prompt.schema_version == "5.0.0"
    assert output == assemble_internal_final_prompt_v5(
        result.snapshot, dictionary=dictionary, templates=templates
    )
    assert CanonicalFinalPromptAssemblyV5.model_validate_json(output.model_dump_json()) == output
    handoff = build_internal_final_prompt_handoff(output)
    assert handoff.schema_version == "5.0.0"
    assert (
        CanonicalInternalFinalPromptHandoffV5.model_validate_json(handoff.model_dump_json())
        == handoff
    )
    for prepare in (build_generation_preparation, build_generation_preparation_v2):
        with pytest.raises(GenerationPreparationError) as failure:
            prepare(handoff, {}, preparation_id=uuid4(), created_at=None)
        assert failure.value.code.value == "unsupported_source_version"
    for key in ("content_hash", "description_content_hash", "product_state_revision_id"):
        bad = deepcopy(output.model_dump(mode="json"))
        bad["internal_final_prompt"][key] = "0" * 64 if "hash" in key else str(uuid4())
        with pytest.raises(ValidationError):
            CanonicalFinalPromptAssemblyV5.model_validate_json(json.dumps(bad))
    forged = result.snapshot.model_copy(
        update={"revision": result.snapshot.revision.model_copy(update={"revision_id": uuid4()})}
    )
    with pytest.raises(ValidationError):
        assemble_internal_final_prompt_v5(forged, dictionary=dictionary, templates=templates)


def test_capacity_and_duplicate_coverage_fail_closed(ring, templates, runtime, dictionary):
    from jewelai_prompts.downstream_preparation import GenerationPreparationError

    result = render(ring, templates, runtime, dictionary, {}, "ru")
    fact = result.assembly.internal_final_prompt.design_facts[0]
    huge = fact.model_copy(update={"target": "style", "value": "я" * 20001})
    with pytest.raises(GenerationPreparationError) as failure:
        render_review_description(result.snapshot, (huge,), (), (), dictionary=dictionary)
    assert failure.value.code.value == "preparation_capacity_exceeded"
    assert "яяяя" not in str(failure.value)
    with pytest.raises(ValueError, match="duplicate"):
        render_review_description(result.snapshot, (fact, fact), (), (), dictionary=dictionary)
