"""Real consumer integration: sequential policy state never replaces LOCK authority."""

from copy import deepcopy
from pathlib import Path

import pytest
from jewelai_domain.knowledge_library import CompiledKnowledgeLibrary
from jewelai_domain.knowledge_policy import (
    KnowledgePolicyEngine,
    RuntimeProvenance,
    RuntimeSemanticState,
)
from jewelai_domain.models import DesignRevision
from jewelai_domain.models_v1_1 import DesignRevisionV1_1, upgrade_design_revision_v1_to_v1_1

from jewelai_prompts import EnrichmentProposal, enrich_prompt, load_prompt_templates

ROOT = Path(__file__).resolve().parents[3]


def inputs(parent):
    ring = DesignRevision.model_validate_json(
        (ROOT / "specs/jewelry-design-schema/fixtures/valid/ring.json").read_text()
    )
    seed = upgrade_design_revision_v1_to_v1_1(ring)
    data = seed.model_dump(mode="json")

    def explicit(value, locked=False):
        return dict(
            availability="value",
            origin="explicit",
            value=value,
            source=ring.event.source.model_dump(mode="json"),
            confirmed=locked,
            locked=locked,
        )

    data["design"]["composition"] = explicit(
        {
            "symmetry_mode": explicit("asymmetrical", not parent),
            "rhythm": explicit("regular"),
        },
        parent,
    )
    revision = DesignRevisionV1_1.model_validate(data)
    runtime = CompiledKnowledgeLibrary(
        package_id="test.canonical.enrichment",
        artifact_version="1.0.0",
        sources=(),
        claims=(),
        domain_knowledge=(),
        language_mappings=(),
        policies=(),
    )
    templates = load_prompt_templates(ROOT / "data/prompts/v1.0.0.json")
    return revision, runtime, templates


def change(target, value, source="user"):
    return EnrichmentProposal(
        target=target,
        value=value,
        source_id=source,
        semantic_state=RuntimeSemanticState.EXPLICIT,
        provenance=RuntimeProvenance.USER_EXPLICIT_LATEST,
    )


@pytest.mark.parametrize("parent", [False, True])
def test_sequential_proposals_retain_original_canonical_locks(parent, monkeypatch):
    revision, runtime, templates = inputs(parent)
    before = revision.model_dump_json()

    def forbid_flat(*args, **kwargs):
        raise AssertionError("The real consumer must not use flat policy evaluation")

    monkeypatch.setattr(KnowledgePolicyEngine, "evaluate", forbid_flat)
    # First an allowed fact, then the canonical locked child/ancestor.
    result = enrich_prompt(
        revision,
        templates,
        runtime,
        proposals=(
            change("center_stone.color", "blue"),
            change("composition.symmetry_mode", "radial"),
        ),
    )
    decisions = {item.target: item for item in result.decisions}
    assert decisions["center_stone.color"].outcome == "APPLIED"
    assert decisions["composition.symmetry_mode"].outcome == "BLOCKED"
    assert decisions["composition.symmetry_mode"].reason == "locked"
    cell = next(item for item in result.final_matrix if item.target == "composition.symmetry_mode")
    assert cell.value == "asymmetrical"
    assert cell.locked is (not parent)
    assert revision.model_dump_json() == before
    assert result == enrich_prompt(
        revision,
        templates,
        runtime,
        proposals=tuple(
            reversed(
                (
                    change("center_stone.color", "blue"),
                    change("composition.symmetry_mode", "radial"),
                )
            )
        ),
    )


def test_effective_aggregate_then_descendant_keeps_canonical_authority():
    revision, runtime, templates = inputs(False)
    replacement = deepcopy(revision.design.composition.value.model_dump(mode="json"))
    replacement["rhythm"]["value"] = "alternating"
    result = enrich_prompt(
        revision,
        templates,
        runtime,
        proposals=(
            change("composition", replacement),
            change("composition.symmetry_mode", "radial"),
        ),
    )
    assert [(item.outcome, item.reason) for item in result.decisions] == [
        ("APPLIED", "higher_or_equal_precedence"),
        ("BLOCKED", "locked"),
    ]
    assert revision.design.composition.value.rhythm.value == "regular"
    assert (
        next(
            item for item in result.final_matrix if item.target == "composition.symmetry_mode"
        ).value
        == "asymmetrical"
    )
