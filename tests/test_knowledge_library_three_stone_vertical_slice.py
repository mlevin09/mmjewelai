import json
from pathlib import Path

from jewelai_domain import (
    ProductionValidationCheck,
    ProductionValidationReport,
    ValidationOutcome,
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
    names = (
        "compiler_contract",
        "provenance_integrity",
        "language_matcher",
        "runtime_policy",
        "prompt_enrichment_integration",
        "behavioral_regression",
    )
    checks = tuple(
        ProductionValidationCheck(
            name=name,
            outcome=ValidationOutcome.PASS,
            evidence_ref=f"STEP15-{index:02d}",
            details="Second vertical slice passed.",
        )
        for index, name in enumerate(names, start=1)
    )
    return ProductionValidationReport(
        package_id=runtime.package_id,
        artifact_version=runtime.artifact_version,
        runtime_sha256=runtime.sha256,
        checks=checks,
    )
