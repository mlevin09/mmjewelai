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
from pydantic import ValidationError

from jewelai_prompts import (
    EnrichmentDecision,
    EnrichmentMatrixCell,
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
    assert first.enrichment_version == "1.2.0"


def test_lower_precedence_enrichment_cannot_overwrite_user_shape(ring, templates, runtime):
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
                source_id="POL-SHAPE",
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
                source_id="DEC-1",
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
                source_id="DEC-1",
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
                provenance=RuntimeProvenance.USER_CONFIRMED,
                value="marquise",
                source_id="ENRICH-SIDE",
            ),
        ),
    )
    assert valid.decisions[0].outcome == "APPLIED"
    assert valid.decisions[0].applicable_policy_ids == ("POL-SIDE-SHAPE",)

    unknown = enrich_prompt(
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
    assert unknown.decisions[0].outcome == "BLOCKED"
    assert unknown.decisions[0].reason == "unknown_target"


def test_blocked_unknown_target_does_not_pollute_final_matrix(ring, templates, runtime):
    result = enrich_prompt(
        ring,
        templates,
        runtime,
        proposals=(
            EnrichmentProposal(
                target="references",
                semantic_state=RuntimeSemanticState.RECOMMENDED,
                provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
                value="basket",
                source_id="DEC-1",
            ),
            EnrichmentProposal(
                target="side_stones.unknown.stones.shape",
                semantic_state=RuntimeSemanticState.NORMALIZED,
                provenance=RuntimeProvenance.NORMALIZED_FROM_USER,
                value="marquise",
                source_id="ENRICH-UNKNOWN-GROUP",
            ),
        ),
    )

    assert {decision.outcome for decision in result.decisions} == {"BLOCKED"}
    final_targets = {cell.target for cell in result.final_matrix}
    assert "references" not in final_targets
    assert "side_stones.unknown.stones.shape" not in final_targets


def test_decisions_retain_exact_proposal_evidence_for_later_persistence(ring, templates, runtime):
    proposals = (
        EnrichmentProposal(
            target="center_stone.setting",
            semantic_state=RuntimeSemanticState.RECOMMENDED,
            provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
            value="prong_setting",
            source_id="DEC-1",
        ),
        EnrichmentProposal(
            target="center_stone.shape",
            semantic_state=RuntimeSemanticState.RECOMMENDED,
            provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
            value="round",
            source_id="POL-SHAPE",
            preservation=PreservationIntent.KEEP,
        ),
        EnrichmentProposal(
            target="metal.color",
            semantic_state=RuntimeSemanticState.NORMALIZED,
            provenance=RuntimeProvenance.NORMALIZED_FROM_USER,
            value="yellow",
            source_id="MESSAGE-1",
        ),
        EnrichmentProposal(
            target="side_stones.unknown.stones.shape",
            semantic_state=RuntimeSemanticState.NORMALIZED,
            provenance=RuntimeProvenance.NORMALIZED_FROM_USER,
            value="marquise",
            source_id="MESSAGE-2",
        ),
    )

    result = enrich_prompt(ring, templates, runtime, proposals=proposals)
    assert result == enrich_prompt(ring, templates, runtime, proposals=proposals)
    decisions = {decision.target: decision for decision in result.decisions}
    initial = {cell.target: cell for cell in result.initial_matrix}
    final = {cell.target: cell for cell in result.final_matrix}

    assert decisions["center_stone.setting"].outcome == "APPLIED"
    assert decisions["center_stone.shape"].outcome == "KEPT"
    assert decisions["metal.color"].outcome == "BLOCKED"
    assert decisions["side_stones.unknown.stones.shape"].outcome == "BLOCKED"
    assert {decision.proposal for decision in result.decisions} == set(proposals)
    assert decisions["center_stone.setting"].result.confirmed is False
    assert decisions["center_stone.setting"].result.provenance == (
        RuntimeProvenance.JEWELAI_RECOMMENDED
    )
    assert decisions["center_stone.setting"].result.source_ids == ("DEC-1",)
    assert initial["center_stone.setting"].semantic_state == RuntimeSemanticState.MISSING
    assert final["center_stone.setting"] == decisions["center_stone.setting"].result
    assert final["center_stone.shape"] == initial["center_stone.shape"]
    assert final["metal.color"] == initial["metal.color"]


@pytest.mark.parametrize("source_id", ["", " ", " leading", "trailing "])
def test_enrichment_proposal_requires_an_exact_nonblank_source(source_id):
    with pytest.raises(ValidationError):
        EnrichmentProposal(
            target="center_stone.setting",
            semantic_state=RuntimeSemanticState.RECOMMENDED,
            provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
            value="prong_setting",
            source_id=source_id,
        )


def test_enrichment_proposal_rejects_impossible_authority_pair():
    with pytest.raises(
        ValidationError,
        match="EXPLICIT proposal cannot use KNOWLEDGE_INFERRED provenance",
    ):
        EnrichmentProposal(
            target="center_stone.material",
            semantic_state=RuntimeSemanticState.EXPLICIT,
            provenance=RuntimeProvenance.KNOWLEDGE_INFERRED,
            value="diamond",
            source_id="POL-SHAPE",
        )


def test_enrichment_rejects_foreign_knowledge_source(ring, templates, runtime):
    with pytest.raises(ValueError, match="does not belong to the selected runtime"):
        enrich_prompt(
            ring,
            templates,
            runtime,
            proposals=(
                EnrichmentProposal(
                    target="center_stone.setting",
                    semantic_state=RuntimeSemanticState.RECOMMENDED,
                    provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
                    value="prong_setting",
                    source_id="FOREIGN-RUNTIME-POLICY",
                ),
            ),
        )


def test_enrichment_decision_rejects_mismatched_target_lineage():
    proposal = EnrichmentProposal(
        target="center_stone.setting",
        semantic_state=RuntimeSemanticState.RECOMMENDED,
        provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
        value="prong_setting",
        source_id="REC-SETTING-1",
    )
    with pytest.raises(ValidationError, match="target lineage mismatch"):
        EnrichmentDecision(
            target="center_stone.shape",
            outcome="APPLIED",
            reason="higher_or_equal_precedence",
            applicable_policy_ids=(),
            proposal=proposal,
            result=EnrichmentMatrixCell(
                target="center_stone.setting",
                semantic_state=RuntimeSemanticState.RECOMMENDED,
                provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
                value="prong_setting",
                confirmed=False,
                locked=False,
                source_ids=("REC-SETTING-1",),
            ),
        )


def test_blocked_proposal_source_remains_part_of_enrichment_content_hash(ring, templates, runtime):
    def blocked(source_id):
        return enrich_prompt(
            ring,
            templates,
            runtime,
            proposals=(
                EnrichmentProposal(
                    target="metal.color",
                    semantic_state=RuntimeSemanticState.NORMALIZED,
                    provenance=RuntimeProvenance.NORMALIZED_FROM_USER,
                    value="yellow",
                    source_id=source_id,
                ),
            ),
        )

    first = blocked("MESSAGE-1")
    second = blocked("MESSAGE-2")

    assert first.decisions[0].outcome == second.decisions[0].outcome == "BLOCKED"
    assert first.decisions[0].result == second.decisions[0].result
    assert first.decisions[0].proposal.source_id == "MESSAGE-1"
    assert second.decisions[0].proposal.source_id == "MESSAGE-2"
    assert first.content_hash != second.content_hash
