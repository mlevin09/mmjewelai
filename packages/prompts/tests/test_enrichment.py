import hashlib
import json
from pathlib import Path

import pytest
from jewelai_domain.knowledge_library import CompiledKnowledgeLibrary, CompiledPolicy
from jewelai_domain.knowledge_policy import (
    PreservationIntent,
    RuntimeProvenance,
    RuntimeSemanticState,
)
from jewelai_domain.models import DesignRevision

from jewelai_prompts import (
    EnrichmentProposal,
    enrich_prompt,
    load_prompt_templates,
)

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = ROOT / "data" / "prompts" / "v1.0.0.json"
RING = ROOT / "specs" / "jewelry-design-schema" / "fixtures" / "valid" / "ring.json"


@pytest.fixture
def ring():
    return DesignRevision.model_validate_json(RING.read_text())


@pytest.fixture
def templates():
    return load_prompt_templates(TEMPLATE)


@pytest.fixture
def runtime():
    return CompiledKnowledgeLibrary(
        package_id="jewelai.test.prompt-enrichment",
        artifact_version="1.0.0",
        sources=(),
        claims=(),
        domain_knowledge=(),
        language_mappings=(),
        policies=(
            CompiledPolicy(
                policy_id="POL-SHAPE",
                target="center_stone.shape",
                effect="Preserve explicit shape over lower-precedence recommendations.",
                source_kind="INTERNAL_PRODUCT_DECISION",
                source_refs=("DEC-1",),
            ),
            CompiledPolicy(
                policy_id="POL-SIDE-SHAPE",
                target="side_stones.{group_id}.stones.shape",
                effect="Address only an existing stable side-stone group.",
                source_kind="INTERNAL_PRODUCT_DECISION",
                source_refs=("DEC-1",),
            ),
        ),
    )


def test_enrichment_matrix_is_deterministic_and_pinned(ring, templates, runtime):
    first = enrich_prompt(ring, templates, runtime)
    second = enrich_prompt(ring, templates, runtime)
    assert first == second
    assert first.knowledge_runtime_sha256 == runtime.sha256
    assert first.knowledge_package_id == runtime.package_id
    assert tuple(item.target for item in first.final_matrix) == tuple(
        sorted(item.target for item in first.final_matrix)
    )
    payload = first.model_dump(mode="json", exclude={"content_hash"})
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert first.content_hash == hashlib.sha256(canonical.encode()).hexdigest()


def test_lower_precedence_enrichment_cannot_overwrite_user_shape(
    ring, templates, runtime
):
    result = enrich_prompt(
        ring,
        templates,
        runtime,
        proposals=(
            EnrichmentProposal(
                target="center_stone.shape",
                semantic_state=RuntimeSemanticState.RECOMMENDED,
                provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
                value="round",
                source_id="ENRICH-1",
            ),
        ),
    )
    decision = result.decisions[0]
    assert decision.outcome == "KEPT"
    assert decision.reason == "lower_precedence"
    assert decision.result.value == "oval"
    assert decision.applicable_policy_ids == ("POL-SHAPE",)


def test_enrichment_does_not_mutate_canonical_revision_or_prompt(ring, templates, runtime):
    baseline = enrich_prompt(ring, templates, runtime)
    enriched = enrich_prompt(
        ring,
        templates,
        runtime,
        proposals=(
            EnrichmentProposal(
                target="center_stone.setting",
                semantic_state=RuntimeSemanticState.RECOMMENDED,
                provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
                value="prong_setting",
                source_id="ENRICH-SETTING",
            ),
        ),
    )
    assert enriched.decisions[0].outcome == "APPLIED"
    assert enriched.decisions[0].result.value == "prong_setting"
    assert enriched.compiled_prompt == baseline.compiled_prompt
    assert "center_stone.setting" not in enriched.compiled_prompt.prompt_text


def test_keep_and_locked_semantics_are_preserved(ring, templates, runtime):
    keep = enrich_prompt(
        ring,
        templates,
        runtime,
        proposals=(
            EnrichmentProposal(
                target="center_stone.setting",
                semantic_state=RuntimeSemanticState.RECOMMENDED,
                provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
                value="prong_setting",
                source_id="ENRICH-KEEP",
                preservation=PreservationIntent.KEEP,
            ),
        ),
    )
    assert keep.decisions[0].outcome == "KEPT"
    assert keep.decisions[0].reason == "preserve_keep"

    locked = enrich_prompt(
        ring,
        templates,
        runtime,
        proposals=(
            EnrichmentProposal(
                target="metal.color",
                semantic_state=RuntimeSemanticState.NORMALIZED,
                provenance=RuntimeProvenance.USER_CONFIRMED,
                value="yellow",
                source_id="ENRICH-LOCKED",
            ),
        ),
    )
    assert locked.decisions[0].outcome == "BLOCKED"
    assert locked.decisions[0].reason == "locked"
    assert locked.decisions[0].result.value == "white"


def test_existing_side_group_is_addressable_but_unknown_group_fails_closed(
    ring, templates, runtime
):
    valid = enrich_prompt(
        ring,
        templates,
        runtime,
        proposals=(
            EnrichmentProposal(
                target="side_stones.accents.stones.shape",
                semantic_state=RuntimeSemanticState.NORMALIZED,
                provenance=RuntimeProvenance.NORMALIZED_FROM_USER,
                value="marquise",
                source_id="ENRICH-SIDE",
            ),
        ),
    )
    assert valid.decisions[0].outcome == "APPLIED"
    assert valid.decisions[0].applicable_policy_ids == ("POL-SIDE-SHAPE",)

    with pytest.raises(ValueError, match="unknown_target"):
        enrich_prompt(
            ring,
            templates,
            runtime,
            proposals=(
                EnrichmentProposal(
                    target="side_stones.unknown.stones.shape",
                    semantic_state=RuntimeSemanticState.NORMALIZED,
                    provenance=RuntimeProvenance.NORMALIZED_FROM_USER,
                    value="marquise",
                    source_id="ENRICH-UNKNOWN",
                ),
            ),
        )
