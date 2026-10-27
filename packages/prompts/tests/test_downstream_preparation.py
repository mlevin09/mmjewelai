"""Pure staged contracts: synthetic evidence, never a production release or live writer."""

import hashlib
import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import UUID

import pytest
from jewelai_domain.models import DesignRevision
from jewelai_domain.models_v1_1 import DesignRevisionV1_1, upgrade_design_revision_v1_to_v1_1
from pydantic import ValidationError
from test_final_prompt import (
    CYCLE_ID,
    ORGANIZATION_ID,
    ROOT,
    SESSION_ID,
    _assemble,
    _constraint_evidence,
    _ready,
)
from test_final_prompt import (
    dictionary as dictionary,
)
from test_final_prompt import (
    runtime as runtime,
)
from test_final_prompt import (
    templates as templates,
)

from jewelai_prompts import build_internal_final_prompt_handoff, compile_prompt
from jewelai_prompts.downstream_preparation import (
    CanonicalInternalFinalPrompt,
    CanonicalInternalFinalPromptHandoff,
    GenerationPreparation,
    GenerationPreparationError,
    PreparationGateEvidence,
    build_generation_preparation,
    canonical_bytes,
    preparation_hash,
    render_canonical_source_text,
    source_content_hash,
)
from jewelai_prompts.revision_projection import project_revision

PREPARATION_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
CREATED_AT = datetime(2026, 10, 27, 12, 30, tzinfo=UTC)


@pytest.fixture
def ring():
    payload = json.loads(
        (ROOT / "specs/jewelry-design-schema/fixtures/valid/ring.json").read_bytes()
    )
    # B1 text-only fixture; the unmodified image-reference fixture is separately rejected.
    payload["design"]["references"]["value"] = []
    return DesignRevision.model_validate(payload)


def stage(assembly, revision, *, references=(), disclosures=None):
    """Test-only successor construction, NOT a replacement runtime writer."""
    prompt = assembly.internal_final_prompt.model_dump(mode="json", exclude={"content_hash"})
    prompt.update(
        schema_version="2.0.0",
        description=assembly.description.model_dump(mode="json"),
        parametric_references=[r.model_dump(mode="json") for r in references],
        disclosures=[
            d.model_dump(mode="json")
            for d in (
                project_revision(revision).disclosures if disclosures is None else disclosures
            )
        ],
    )
    unchecked = CanonicalInternalFinalPrompt.model_construct(
        **{
            **assembly.internal_final_prompt.__dict__,
            "schema_version": "2.0.0",
            "description": assembly.description,
            "parametric_references": tuple(references),
            "disclosures": (),
        }
    )
    prompt["prompt_text"] = render_canonical_source_text(unchecked)
    prompt["content_hash"] = source_content_hash(prompt)
    source = build_internal_final_prompt_handoff(assembly).model_dump(
        mode="json", exclude={"content_hash"}
    )
    source.update(
        schema_version="2.0.0",
        internal_final_prompt_schema_version="2.0.0",
        internal_final_prompt=prompt,
        internal_final_prompt_content_hash=prompt["content_hash"],
    )
    source["content_hash"] = source_content_hash(source)
    return CanonicalInternalFinalPromptHandoff.model_validate(source)


def gate_for(source, revision, **changes):
    frontier = {"answers": [], "corrections": []}
    payload = dict(
        organization_id=ORGANIZATION_ID,
        session_id=SESSION_ID,
        revision=revision,
        enrichment_cycle_id=CYCLE_ID,
        enrichment_cycle_number=2,
        enrichment_result_hash=source.internal_final_prompt.enrichment_result_content_hash,
        source_handoff_hash=source.content_hash,
        knowledge_release=source.knowledge_release,
        rule_decision=_ready(),
        workflow_status="final_output_" + source.readiness.value,
        clarification_plan_id=PREPARATION_ID,
        clarification_plan_hash="c" * 64,
        blocking_clarification_ids=(),
        decision_frontier=frontier,
        decision_frontier_hash=preparation_hash("jewelai.preparation.frontier/1.0.0", frontier),
        release_verified=True,
    )
    payload.update(changes)
    return PreparationGateEvidence(**payload)


def prepare(source, revision, **gate_changes):
    return build_generation_preparation(
        source,
        gate_for(source, revision, **gate_changes),
        preparation_id=PREPARATION_ID,
        created_at=CREATED_AT,
    )


def rehash_source(source, mutate):
    data = source.model_dump(mode="json")
    mutate(data["internal_final_prompt"])
    p = data["internal_final_prompt"]
    p.pop("content_hash")
    from jewelai_prompts.final_prompt import FinalPromptConstraint, FinalPromptDesignFact

    unchecked = source.internal_final_prompt.model_copy(
        update={
            "design_facts": tuple(FinalPromptDesignFact(**f) for f in p["design_facts"]),
            "constraints": tuple(FinalPromptConstraint(**c) for c in p["constraints"]),
        }
    )
    p["prompt_text"] = render_canonical_source_text(unchecked)
    p["content_hash"] = source_content_hash(p)
    data["internal_final_prompt_content_hash"] = p["content_hash"]
    data.pop("content_hash")
    data["content_hash"] = source_content_hash(data)
    return data


def test_no_halo_pure_preparation(ring, templates, runtime, dictionary):
    evidence = _constraint_evidence(ring, instruction="Do not add a halo.")
    source = stage(
        _assemble(ring, templates, runtime, dictionary, constraint_evidence=(evidence,)), ring
    )
    original = ring.model_dump_json()
    first = prepare(source, ring)
    second = prepare(source, ring)
    assert first.canonical == second.canonical
    assert first.payload.artifact_hash == (
        "e3af3b751714c33a6feaa2013a2dfa3a54183934c5036da6e5eb4d2188ef1508"
    )
    assert hashlib.sha256(first.canonical).hexdigest() == (
        "17c61309312cf4b369a8c5d91a3400373bc384a8d1f20a7916acdcd8c77b127c"
    )
    assert GenerationPreparation.model_validate_json(first.canonical) == first
    text = first.payload.execution.rendering_text
    assert 'PROHIBITION feature.halo = null; instruction="Do not add a halo."' in text
    assert "KEEP metal.color" in text and "locked=true" in text
    assert str(SESSION_ID) not in text and evidence.evidence_id not in text
    assert ring.model_dump_json() == original


def test_exact_semantic_coverage_and_defensive_immutability(ring, templates, runtime, dictionary):
    source = stage(_assemble(ring, templates, runtime, dictionary), ring)
    artifact = prepare(source, ring)
    prompt = source.internal_final_prompt
    expected = {
        f"/internal_final_prompt/{name}/{i}"
        for name in (
            "design_facts",
            "constraints",
            "parametric_references",
            "disclosures",
            "unresolved_details",
        )
        for i in range(len(getattr(prompt, name)))
    }
    coverage = artifact.payload.execution.semantic_coverage
    assert {c.source_pointer for c in coverage} == expected
    assert len(coverage) == len(expected)
    assert all(
        artifact.payload.execution.rendering_text.splitlines()[c.rendered_ordinal - 1]
        for c in coverage
    )
    with pytest.raises(FrozenInstanceError):
        artifact.canonical = b"{}"
    view = artifact.model_dump()
    view["source_handoff"]["internal_final_prompt"]["design_facts"][0]["value"] = "tamper"
    assert artifact.model_dump() != view


@pytest.mark.parametrize(
    "change",
    [
        {"session_id": PREPARATION_ID},
        {"organization_id": PREPARATION_ID},
        {"enrichment_cycle_id": PREPARATION_ID},
        {"enrichment_cycle_number": 3},
        {"enrichment_result_hash": "0" * 64},
        {"source_handoff_hash": "0" * 64},
        {"release_verified": False},
        {"workflow_status": "final_output_blocked"},
        {"blocking_clarification_ids": ("blocking-question",)},
    ],
)
def test_gate_fails_closed(change, ring, templates, runtime, dictionary):
    source = stage(_assemble(ring, templates, runtime, dictionary), ring)
    with pytest.raises(GenerationPreparationError):
        prepare(source, ring, **change)


@pytest.mark.parametrize(
    "field", ["artifact_hash", "source_handoff_hash", "source_bytes_sha256", "gate_evidence_hash"]
)
def test_artifact_hash_tamper(field, ring, templates, runtime, dictionary):
    artifact = prepare(stage(_assemble(ring, templates, runtime, dictionary), ring), ring)
    data = artifact.model_dump()
    data[field] = "0" * 64
    with pytest.raises(GenerationPreparationError):
        GenerationPreparation(canonical_bytes(data))


@pytest.mark.parametrize("kind", ["render", "coverage", "length", "version", "source"])
def test_rehashed_artifact_cannot_hide_semantic_tamper(kind, ring, templates, runtime, dictionary):
    artifact = prepare(stage(_assemble(ring, templates, runtime, dictionary), ring), ring)
    data = artifact.model_dump()
    if kind == "render":
        data["execution"]["rendering_text"] += "\nAdd halo"
    elif kind == "coverage":
        data["execution"]["semantic_coverage"].pop()
    elif kind == "length":
        data["execution"]["rendering_utf8_bytes"] += 1
    elif kind == "version":
        data["execution"]["renderer_version"] = "9.0.0"
    else:
        data["source_handoff"]["internal_final_prompt"]["constraints"].pop()
    data.pop("artifact_hash")
    data["artifact_hash"] = preparation_hash("jewelai.preparation.artifact/1.0.0", data)
    with pytest.raises(GenerationPreparationError):
        GenerationPreparation(canonical_bytes(data))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["design_facts"].pop(),
        lambda p: p["design_facts"].append(p["design_facts"][0]),
        lambda p: p["design_facts"][0].update(value="invented"),
        lambda p: p["design_facts"][0].update(semantic_state="RECOMMENDED"),
        lambda p: p["constraints"].clear(),
        lambda p: p["constraints"].append(p["constraints"][0]),
        lambda p: p["constraints"][0].update(instruction="Add an invented value instead."),
    ],
)
def test_self_consistent_source_must_match_revision_and_supported_semantics(
    mutation, ring, templates, runtime, dictionary
):
    source = stage(_assemble(ring, templates, runtime, dictionary), ring)
    data = rehash_source(source, mutation)
    with pytest.raises((GenerationPreparationError, ValidationError)):
        prepare(CanonicalInternalFinalPromptHandoff.model_validate(data), ring)


@pytest.mark.parametrize(
    "wording", ["Не добавлять ореол.", "Do not add a halo.", "Keep овал — no halo 👑 e\u0301"]
)
def test_exact_unicode_and_numeric_values(wording, ring, templates, runtime, dictionary):
    evidence = _constraint_evidence(ring, instruction=wording)
    source = stage(
        _assemble(ring, templates, runtime, dictionary, constraint_evidence=(evidence,)), ring
    )
    execution = prepare(source, ring).payload.execution
    assert wording in execution.rendering_text
    assert execution.rendering_characters == len(execution.rendering_text)
    assert execution.rendering_utf8_bytes == len(execution.rendering_text.encode("utf-8"))
    assert canonical_bytes([1, 1.0, -0.0, "e\u0301"]) == '[1,1.0,-0.0,"e\u0301"]'.encode()


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":"1.0.0","schema_version":"1.0.0"}',
        b'{"a":NaN}',
        b"[]",
        b'{"a":"\\ud800"}',
    ],
)
def test_invalid_canonical_inputs_rejected(raw):
    with pytest.raises(GenerationPreparationError):
        GenerationPreparation(raw)


GOLDEN = {
    "assumption-and-inapplicable": (
        "46c6bc6669c2ec5bb7c56a80869fb5f16cfbfba1d1adf956e7ea1192eebae6b3"
    ),
    "derived-dimensions": "7dded820477db4cfb05acd153902133c453f8584b08680d1ac0cca0c75ea6fc4",
    "empty-intake": "ba7f6fd8d48daa4f01b8195d50e801ed5047f8b114c0f20d386c4ca1d5bae110",
    "ring": "00716bb071491733a8a3024d0b82096a70c69e20c756a300d4bf2ae148a31041",
}


@pytest.mark.parametrize("name", GOLDEN)
def test_legacy_exact_serialized_golden(name, templates):
    revision = DesignRevision.model_validate_json(
        (ROOT / "specs/jewelry-design-schema/fixtures/valid" / f"{name}.json").read_bytes()
    )
    legacy = compile_prompt(revision, templates)
    assert hashlib.sha256(legacy.model_dump_json().encode()).hexdigest() == GOLDEN[name]
    projection = project_revision(revision)
    assert projection.specification_entries == legacy.specification_entries
    assert projection.locked_constraints == legacy.locked_constraints
    assert projection.disclosures == legacy.disclosures


def test_image_reference_is_explicitly_unsupported_not_silently_dropped(
    templates, runtime, dictionary
):
    raw = DesignRevision.model_validate_json(
        (ROOT / "specs/jewelry-design-schema/fixtures/valid/ring.json").read_bytes()
    )
    source = stage(_assemble(raw, templates, runtime, dictionary), raw)
    with pytest.raises(GenerationPreparationError, match="unsupported_source_semantics"):
        prepare(source, raw)


def test_not_applicable_and_assumption_disclosures(templates, runtime, dictionary):
    payload = json.loads(
        (
            ROOT / "specs/jewelry-design-schema/fixtures/valid/assumption-and-inapplicable.json"
        ).read_bytes()
    )
    payload["design"]["references"]["value"] = []
    revision = DesignRevision.model_validate(payload)
    source = stage(_assemble(revision, templates, runtime, dictionary), revision)
    text = prepare(source, revision).payload.execution.rendering_text
    for disclosure in project_revision(revision).disclosures:
        assert disclosure.concrete_target in text
        for field in ("reason", "rationale", "uncertainty"):
            value = getattr(disclosure, field)
            if value:
                assert value in text
    assert "PROHIBITION" in text and "NOT_APPLICABLE" in text
    data = rehash_source(source, lambda p: p.update(disclosures=[]))
    with pytest.raises(GenerationPreparationError):
        prepare(CanonicalInternalFinalPromptHandoff.model_validate(data), revision)


def test_superseded_rejected_and_unresolved_constraints(ring, templates, runtime, dictionary):
    current = _constraint_evidence(
        ring,
        evidence_id="constraint_222222222222222222222222",
        instruction="Keep the design without a halo.",
    )
    old = _constraint_evidence(
        ring, status="superseded", instruction="Add a halo.", superseded_by=current.evidence_id
    )
    rejected = _constraint_evidence(
        ring,
        status="rejected",
        evidence_id="constraint_333333333333333333333333",
        instruction="Add a yellow border.",
        subject="feature.border",
    )
    unresolved = _constraint_evidence(
        ring,
        status="unresolved",
        evidence_id="constraint_444444444444444444444444",
        instruction="Add an invented detail.",
        subject="feature.unknown",
    )
    evidence = (old, current, rejected, unresolved)
    source = stage(
        _assemble(ring, templates, runtime, dictionary, constraint_evidence=evidence), ring
    )
    text = prepare(source, ring).payload.execution.rendering_text
    assert "Keep the design without a halo." in text
    assert "Add a halo." not in text and "Add a yellow border." not in text
    assert "Add an invented detail." not in text
    assert "feature.unknown: ambiguous; not an accepted requirement" in text
    assert (
        prepare(source, ring).payload.source_handoff.internal_final_prompt.constraint_evidence
        == evidence
    )


def test_recommendation_is_not_accepted(ring, templates, runtime, dictionary):
    from jewelai_domain.knowledge_policy import RuntimeProvenance, RuntimeSemanticState
    from test_final_prompt import _snapshot, _verified_enrichment

    from jewelai_prompts import EnrichmentProposal, assemble_internal_final_prompt

    proposal = EnrichmentProposal(
        target="center_stone.setting",
        value="prong_setting",
        source_id="DEC-1",
        semantic_state=RuntimeSemanticState.RECOMMENDED,
        provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
    )
    enrichment = _verified_enrichment(ring, templates, runtime, proposals=(proposal,))
    assembly = assemble_internal_final_prompt(
        _snapshot(ring, enrichment), dictionary=dictionary, templates=templates
    )
    source = stage(assembly, ring)
    text = prepare(source, ring).payload.execution.rendering_text
    assert "center_stone.setting: unaccepted_recommendation" in text
    assert "prong_setting" not in text
    assert not source.internal_final_prompt.enrichment_evidence[0].accepted_as_requirement


def test_accepted_correction_keeps_current_value_and_exact_lineage(
    ring, templates, runtime, dictionary
):
    from test_final_prompt import REPORT_HASH, _changed

    from jewelai_prompts import FinalPromptDecisionLineage

    revision = _changed(
        ring, lambda design: design["center_stone"]["shape"].update(value="emerald_cut")
    )
    lineage = FinalPromptDecisionLineage(
        kind="correction",
        session_id=SESSION_ID,
        decision_id="correction-shape",
        decision="CORRECT",
        outcome="APPLIED",
        target="center_stone.shape",
        selected_value="emerald_cut",
        source_revision_id=ring.revision_id,
        resulting_revision_id=revision.revision_id,
        applies_to_revision_id=revision.revision_id,
        knowledge_package_id=runtime.package_id,
        knowledge_artifact_version=runtime.artifact_version,
        knowledge_runtime_sha256=runtime.sha256,
        knowledge_validation_report_sha256=REPORT_HASH,
        content_hash="d" * 64,
    )
    source = stage(
        _assemble(revision, templates, runtime, dictionary, lineage=(lineage,)), revision
    )
    artifact = prepare(source, revision)
    assert 'FACT center_stone.shape = "emerald_cut"' in artifact.payload.execution.rendering_text
    assert artifact.payload.source_handoff.internal_final_prompt.decision_lineage == (lineage,)


def test_parametric_reference_stays_advisory(ring, templates, runtime, dictionary):
    from jewelai_prompts import ParametricEnrichmentReference, ParametricReferenceDimensions

    ref = ParametricEnrichmentReference(
        target="center_stone.dimensions",
        material_id=ring.design.center_stone.material.value,
        shape_id="oval",
        weight_ct=ring.design.center_stone.weight.value.value,
        dimensions=ParametricReferenceDimensions(length_mm=7.5, width_mm=5.0),
        estimate_kind="APPROXIMATE_CALIBRATION",
        record_ids=("CAL-PRIVATE",),
        source_ids=("SRC-PRIVATE",),
        applicability=("Loose faceted stone only.",),
        uncertainty=("Actual depth and proportions vary.",),
    )
    source = stage(_assemble(ring, templates, runtime, dictionary), ring, references=(ref,))
    text = prepare(source, ring).payload.execution.rendering_text
    assert "REFERENCE ONLY (not a requirement)" in text
    assert "Actual depth and proportions vary." in text and '"length_mm":7.5' in text
    assert "CAL-PRIVATE" not in text and "SRC-PRIVATE" not in text
    assert "FACT center_stone.dimensions" not in text


def multi_component_source(ring, templates, runtime, dictionary):
    from jewelai_prompts.final_prompt import FinalPromptConstraint, FinalPromptDesignFact

    data = upgrade_design_revision_v1_to_v1_1(ring).model_dump(mode="json")

    def explicit(value, **flags):
        return {
            "availability": "value",
            "origin": "explicit",
            "value": value,
            "source": data["event"]["source"],
            "confirmed": True,
            "locked": False,
            **flags,
        }

    data["design"]["metal"]["components"] = explicit(
        [
            {"component_id": "z_head", "material": explicit("platinum", locked=True)},
            {"component_id": "a_shank", "material": explicit("gold")},
        ]
    )
    data["design"]["decorative_elements"] = explicit(
        [
            {"element_id": "filigree", "motif": explicit("floral")},
        ]
    )
    revision = DesignRevisionV1_1.model_validate(data)
    projection = project_revision(revision)
    # Stage source from real typed projection; do not invoke the legacy text-size-limited compiler.
    old_source = stage(_assemble(ring, templates, runtime, dictionary), ring)
    prompt = old_source.internal_final_prompt
    facts = tuple(
        FinalPromptDesignFact(
            target=e.concrete_target,
            applicability=e.applicability,
            value=e.value,
            origin=e.origin,
            confirmed=e.confirmed,
            locked=e.locked,
            semantic_state="EXPLICIT",
            provenance="USER_CONFIRMED" if e.confirmed else "USER_EXPLICIT_LATEST",
            source_ids=("example-request",),
        )
        for e in projection.specification_entries
    )
    constraints = []
    for fact in facts:
        constraints.append(
            FinalPromptConstraint(
                kind="requirement",
                target=fact.target,
                value=fact.value,
                instruction="Preserve this authoritative design value.",
            )
        )
        if fact.locked:
            constraints.append(
                FinalPromptConstraint(
                    kind="preservation",
                    target=fact.target,
                    value=fact.value,
                    instruction="This confirmed locked value must not change.",
                )
            )
    changed = prompt.model_copy(
        update={
            "design_facts": facts,
            "constraints": tuple(constraints),
            "artifact_versions": prompt.artifact_versions.model_copy(
                update={"design_schema_version": "1.1.0"}
            ),
        }
    )
    payload = rehash_source(
        old_source,
        lambda p: p.update(
            design_facts=[f.model_dump(mode="json") for f in facts],
            constraints=[c.model_dump(mode="json") for c in constraints],
            artifact_versions=changed.artifact_versions.model_dump(mode="json"),
        ),
    )
    source = CanonicalInternalFinalPromptHandoff.model_validate(payload)
    return source, revision


def test_multi_component_projection_and_stable_aliases(ring, templates, runtime, dictionary):
    source, revision = multi_component_source(ring, templates, runtime, dictionary)
    artifact = prepare(source, revision)
    text = artifact.payload.execution.rendering_text
    assert "metal.components.component_1.material" in text
    assert "metal.components.component_2.material" in text
    assert "decorative_elements.element_1.motif" in text
    assert "a_shank" not in text and "z_head" not in text and "filigree" not in text
    assert "example-request" not in text
    assert any(
        f.target == "metal.components.z_head.material"
        for f in source.internal_final_prompt.design_facts
    )  # source IDs unchanged
    assert len(artifact.canonical) < 2_097_152


def test_capacity_boundaries_fail_without_truncation(
    monkeypatch, ring, templates, runtime, dictionary
):
    import jewelai_prompts.downstream_preparation as module

    source = stage(_assemble(ring, templates, runtime, dictionary), ring)
    artifact = prepare(source, ring)
    size = artifact.payload.execution.rendering_characters
    monkeypatch.setattr(module, "RENDER_MAX_CHARACTERS", size)
    assert prepare(source, ring) == artifact
    monkeypatch.setattr(module, "RENDER_MAX_CHARACTERS", size - 1)
    with pytest.raises(GenerationPreparationError, match="preparation_capacity_exceeded"):
        prepare(source, ring)
    monkeypatch.setattr(module, "RENDER_MAX_CHARACTERS", 20_000)
    raw_size = len(canonical_bytes(source)) + len(canonical_bytes(gate_for(source, ring)))
    monkeypatch.setattr(module, "SOURCE_MAX_BYTES", raw_size)
    assert prepare(source, ring) == artifact
    monkeypatch.setattr(module, "SOURCE_MAX_BYTES", raw_size - 1)
    with pytest.raises(GenerationPreparationError):
        prepare(source, ring)
    monkeypatch.setattr(module, "SOURCE_MAX_BYTES", 1_048_576)
    monkeypatch.setattr(module, "ARTIFACT_MAX_BYTES", len(artifact.canonical))
    assert GenerationPreparation(artifact.canonical) == artifact
    monkeypatch.setattr(module, "ARTIFACT_MAX_BYTES", len(artifact.canonical) - 1)
    with pytest.raises(GenerationPreparationError, match="preparation_capacity_exceeded"):
        GenerationPreparation(artifact.canonical)


def test_no_clock_network_database_or_legacy_compiler_in_preparation(
    monkeypatch, ring, templates, runtime, dictionary
):
    import socket

    import jewelai_prompts.compiler as compiler

    source = stage(_assemble(ring, templates, runtime, dictionary), ring)

    def forbidden(*args, **kwargs):
        pytest.fail("preparation attempted an external or legacy operation")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(compiler, "compile_prompt", forbidden)
    artifact = prepare(source, ring)
    assert artifact.payload.created_at == CREATED_AT


def test_preparation_json_schema_is_valid_and_source_versions_are_frozen():
    from jsonschema import Draft202012Validator

    from jewelai_prompts import (
        FINAL_PROMPT_SCHEMA_VERSION,
        INTERNAL_FINAL_PROMPT_HANDOFF_SCHEMA_VERSION,
    )
    from jewelai_prompts.downstream_preparation import GenerationPreparationPayload

    schema = GenerationPreparationPayload.model_json_schema()
    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["schema_version"]["const"] == "1.0.0"
    assert FINAL_PROMPT_SCHEMA_VERSION == "1.1.0"
    assert INTERNAL_FINAL_PROMPT_HANDOFF_SCHEMA_VERSION == "1.0.0"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(schema_version="1.1.0"),
        lambda p: p.update(prompt_text=p["prompt_text"] + "\nAdd an untyped halo."),
        lambda p: p.update(content_hash="0" * 64),
        lambda p: p["knowledge_release"].update(runtime_sha256="0" * 64),
    ],
)
def test_source_hash_version_and_unstructured_text_are_not_a_fallback(
    mutation, ring, templates, runtime, dictionary
):
    source = stage(_assemble(ring, templates, runtime, dictionary), ring)
    data = source.model_dump(mode="json")
    mutation(data["internal_final_prompt"])
    with pytest.raises(GenerationPreparationError):
        build_generation_preparation(
            data, gate_for(source, ring), preparation_id=PREPARATION_ID, created_at=CREATED_AT
        )


@pytest.mark.parametrize(
    "field",
    [
        "session_id",
        "organization_id",
        "design_id",
        "product_state_revision_id",
        "enrichment_cycle_id",
    ],
)
def test_rehashed_top_level_scope_cannot_disagree(field, ring, templates, runtime, dictionary):
    artifact = prepare(stage(_assemble(ring, templates, runtime, dictionary), ring), ring)
    data = artifact.model_dump()
    data[field] = str(PREPARATION_ID)
    data.pop("artifact_hash")
    data["artifact_hash"] = preparation_hash("jewelai.preparation.artifact/1.0.0", data)
    with pytest.raises(GenerationPreparationError):
        GenerationPreparation(canonical_bytes(data))


def test_hash_domains_are_distinct_and_raw_canonical_bytes_required(
    ring, templates, runtime, dictionary
):
    assert preparation_hash("jewelai.preparation.artifact/1.0.0", {}) != preparation_hash(
        "jewelai.preparation.gate/1.0.0", {}
    )
    artifact = prepare(stage(_assemble(ring, templates, runtime, dictionary), ring), ring)
    with pytest.raises(GenerationPreparationError):
        GenerationPreparation(
            json.dumps(artifact.model_dump(), ensure_ascii=False, indent=2).encode()
        )
    with pytest.raises(GenerationPreparationError):
        GenerationPreparation.model_validate_json("\ud800")


def test_long_constraints_and_history_are_retained_without_promoting_history(
    ring, templates, runtime, dictionary
):
    evidence = tuple(
        _constraint_evidence(
            ring,
            evidence_id=f"constraint_{i:024x}",
            status="rejected" if i else "active",
            subject=f"feature.detail_{i}",
            instruction="Preserve this edge. " + "Ж" * 1500,
            original_wording="Synthetic history " + "字" * 1900,
        )
        for i in range(8)
    )
    source = stage(
        _assemble(ring, templates, runtime, dictionary, constraint_evidence=evidence), ring
    )
    artifact = prepare(source, ring)
    assert artifact.payload.source_handoff.internal_final_prompt.constraint_evidence == evidence
    assert artifact.payload.execution.rendering_text.count("Ж" * 1500) == 1
    assert "字" not in artifact.payload.execution.rendering_text
    assert len(canonical_bytes(source)) > artifact.payload.execution.rendering_utf8_bytes


def test_utf8_limit_and_oversize_artifact_are_enforced(
    monkeypatch, ring, templates, runtime, dictionary
):
    import jewelai_prompts.downstream_preparation as module

    source = stage(_assemble(ring, templates, runtime, dictionary), ring)
    artifact = prepare(source, ring)
    size = artifact.payload.execution.rendering_utf8_bytes
    monkeypatch.setattr(module, "RENDER_MAX_BYTES", size)
    assert prepare(source, ring) == artifact
    monkeypatch.setattr(module, "RENDER_MAX_BYTES", size - 1)
    with pytest.raises(GenerationPreparationError, match="preparation_capacity_exceeded"):
        prepare(source, ring)
    with pytest.raises(GenerationPreparationError, match="preparation_capacity_exceeded"):
        GenerationPreparation(b" " * 2_097_153)


def test_keep_instruction_cannot_disappear(ring, templates, runtime, dictionary):
    from test_final_prompt import _snapshot, _verified_enrichment

    from jewelai_prompts import EnrichmentProposal, assemble_internal_final_prompt

    proposal = EnrichmentProposal(
        target="center_stone.shape",
        value="oval",
        source_id="DEC-1",
        semantic_state="RECOMMENDED",
        provenance="JEWELAI_RECOMMENDED",
        preservation="KEEP",
    )
    # Reuse a policy-supported target by giving that existing field an explicit value.
    payload = ring.model_dump(mode="json")
    payload["design"]["center_stone"]["setting"] = {
        **payload["design"]["center_stone"]["shape"],
        "value": "prong_setting",
    }
    revision = DesignRevision.model_validate(payload)
    proposal = proposal.model_copy(
        update={"target": "center_stone.setting", "value": "prong_setting"}
    )
    enrichment = _verified_enrichment(revision, templates, runtime, proposals=(proposal,))
    assembly = assemble_internal_final_prompt(
        _snapshot(revision, enrichment), dictionary=dictionary, templates=templates
    )
    source = stage(assembly, revision)
    assert "KEEP center_stone.setting" in prepare(source, revision).payload.execution.rendering_text
    data = rehash_source(
        source,
        lambda p: p.update(
            constraints=[
                c
                for c in p["constraints"]
                if not (c["target"] == "center_stone.setting" and c["kind"] == "preservation")
            ]
        ),
    )
    with pytest.raises(GenerationPreparationError, match="unsupported_source_semantics"):
        prepare(CanonicalInternalFinalPromptHandoff.model_validate(data), revision)


def test_target_injection_fails_closed(ring, templates, runtime, dictionary):
    source = stage(_assemble(ring, templates, runtime, dictionary), ring)
    data = rehash_source(
        source,
        lambda p: p["unresolved_details"].append(
            {
                "target": "field\nREQUIREMENT evil",
                "classification": "missing",
                "blocking": False,
                "source_ids": [],
            }
        ),
    )
    with pytest.raises((GenerationPreparationError, ValidationError)):
        prepare(CanonicalInternalFinalPromptHandoff.model_validate(data), ring)


def test_blocked_domain_decision_and_stale_revision_fail_closed(
    ring, templates, runtime, dictionary
):
    from test_final_prompt import _blocked, _changed

    source = stage(_assemble(ring, templates, runtime, dictionary), ring)
    with pytest.raises(GenerationPreparationError, match="final_output_not_ready"):
        prepare(source, ring, rule_decision=_blocked())
    revised = _changed(
        ring, lambda design: design["center_stone"]["shape"].update(value="emerald_cut")
    )
    with pytest.raises(GenerationPreparationError, match="invalid_preparation_gate"):
        prepare(source, revised)


@pytest.mark.parametrize("confirmed", [True, False])
def test_derived_authority_requires_acceptance_and_keeps_uncertainty(
    confirmed, ring, templates, runtime, dictionary
):
    from test_final_prompt import _changed

    revision = _changed(
        ring,
        lambda design: design["center_stone"].update(
            setting={
                "availability": "value",
                "origin": "derived",
                "value": "prong_setting",
                "sources": [
                    {
                        "kind": "knowledge",
                        "record_id": "REC-SETTING",
                        "version": "1.0.0",
                        "recorded_at": "2026-09-20T12:00:00Z",
                    }
                ],
                "uncertainty": "Reviewed estimate, not a measured dimension.",
                "confirmed": confirmed,
                "locked": False,
            }
        ),
    )
    source = stage(_assemble(revision, templates, runtime, dictionary), revision)
    if confirmed:
        text = prepare(source, revision).payload.execution.rendering_text
        assert "semantic_state=ACCEPTED; provenance=USER_ACCEPTED_RECOMMENDATION" in text
        assert "Reviewed estimate, not a measured dimension." in text
        assert "REC-SETTING" not in text
    else:
        with pytest.raises(GenerationPreparationError, match="unsupported_source_semantics"):
            prepare(source, revision)


def test_numeric_spelling_cannot_be_replaced_by_python_equal_value(
    ring, templates, runtime, dictionary
):
    source = stage(_assemble(ring, templates, runtime, dictionary), ring)

    def mutate(p):
        fact = next(f for f in p["design_facts"] if f["target"] == "metal.purity")
        assert isinstance(fact["value"]["value"], float)
        fact["value"]["value"] = int(fact["value"]["value"])

    data = rehash_source(source, mutate)
    with pytest.raises(GenerationPreparationError):
        prepare(CanonicalInternalFinalPromptHandoff.model_validate(data), ring)


def test_source_normalization_is_not_silently_accepted(ring, templates, runtime, dictionary):
    evidence = _constraint_evidence(ring)
    source = stage(
        _assemble(ring, templates, runtime, dictionary, constraint_evidence=(evidence,)), ring
    )
    payload = source.model_dump(mode="json")
    # The frozen Text validator would trim this back to the original hashed value.
    payload["internal_final_prompt"]["constraint_evidence"][0]["normalized_instruction"] = (
        " " + evidence.normalized_instruction + " "
    )
    with pytest.raises(GenerationPreparationError):
        build_generation_preparation(
            payload, gate_for(source, ring), preparation_id=PREPARATION_ID, created_at=CREATED_AT
        )
