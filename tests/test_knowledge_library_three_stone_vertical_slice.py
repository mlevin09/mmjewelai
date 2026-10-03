import json
from pathlib import Path

from jewelai_domain import (
    ProductionValidationCheck,
    ProductionValidationReport,
    ProductionValidationStatus,
    RuntimeProvenance,
    RuntimeSemanticState,
    compile_knowledge_library,
    promote_knowledge_runtime,
)
from jewelai_domain.knowledge_storage import KnowledgeArtifactStore
from jewelai_domain.models import DesignRevision
from jewelai_parser import KnowledgeLibraryMatcher, ResolvedKnowledgeMatch
from jewelai_prompts import EnrichmentProposal, enrich_prompt, load_prompt_templates

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "data" / "knowledge" / "v1" / "three-stone-1.0.0.json"
RING = ROOT / "specs" / "jewelry-design-schema" / "fixtures" / "valid" / "ring.json"
PROMPTS = ROOT / "data" / "prompts" / "v1.0.0.json"


def _runtime():
    bundle = json.loads(PACKAGE.read_text(encoding="utf-8"))
    return compile_knowledge_library(bundle)


def _report(runtime):
    checks = tuple(
        ProductionValidationCheck(
            check_id=f"STEP15-{index:02d}",
            category=category,
            status=ProductionValidationStatus.PASS,
            detail="Second vertical slice passed.",
        )
        for index, category in enumerate(
            (
                "compiler",
                "matcher",
                "policy_runtime",
                "enrichment",
                "behavioral_regression",
            ),
            start=1,
        )
    )
    return ProductionValidationReport(
        package_id=runtime.package_id,
        artifact_version=runtime.artifact_version,
        runtime_sha256=runtime.sha256,
        checks=checks,
    )


def test_three_stone_slice_compiles_matches_and_persists(tmp_path):
    bundle = json.loads(PACKAGE.read_text(encoding="utf-8"))
    runtime, manifest = compile_knowledge_library(bundle)
    stored = KnowledgeArtifactStore(tmp_path).publish(bundle)

    assert runtime.package_id == "jewelai.validation.three_stone"
    assert manifest.runtime_sha256 == runtime.sha256
    assert stored.runtime_sha256 == runtime.sha256

    matcher = KnowledgeLibraryMatcher(runtime)
    en = matcher.match("three stone", locale="en")
    ru = matcher.match("трёхкаменное кольцо", locale="ru")
    assert isinstance(en, ResolvedKnowledgeMatch)
    assert isinstance(ru, ResolvedKnowledgeMatch)
    assert en.candidate.concept_id == "style.three_stone"
    assert ru.candidate.concept_id == "style.three_stone"


def test_three_stone_slice_exercises_group_binding_enrichment_and_activation_gate():
    runtime, _ = _runtime()
    ring = DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))
    templates = load_prompt_templates(PROMPTS)

    result = enrich_prompt(
        ring,
        templates,
        runtime,
        proposals=(
            EnrichmentProposal(
                target="side_stones.accents.stones.shape",
                semantic_state=RuntimeSemanticState.NORMALIZED,
                provenance=RuntimeProvenance.USER_CONFIRMED,
                value="marquise",
                source_id="STEP15-SIDE",
            ),
            EnrichmentProposal(
                target="side_stones.not-present.stones.shape",
                semantic_state=RuntimeSemanticState.NORMALIZED,
                provenance=RuntimeProvenance.USER_CONFIRMED,
                value="round",
                source_id="STEP15-UNKNOWN",
            ),
        ),
    )
    decisions = {item.target: item for item in result.decisions}
    assert decisions["side_stones.accents.stones.shape"].outcome == "APPLIED"
    assert decisions["side_stones.not-present.stones.shape"].outcome == "BLOCKED"
    assert decisions["side_stones.not-present.stones.shape"].reason == "unknown_target"

    active = promote_knowledge_runtime(runtime, _report(runtime))
    assert active.runtime_sha256 == runtime.sha256
    assert active.active_for_production is True
