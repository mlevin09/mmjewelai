import json
from pathlib import Path

from jewelai_domain.knowledge_library import (
    Claim,
    DomainKnowledge,
    EvidenceStrength,
    EvidenceTier,
    KnowledgeLibraryBundle,
    LanguageMapping,
    Lifecycle,
    MappingMode,
    MappingQuality,
    Policy,
    Source,
    SourceType,
    compile_knowledge_library,
)
from jewelai_domain.knowledge_policy import (
    RuntimeProvenance,
    RuntimeSemanticState,
    build_knowledge_runtime_state,
)
from jewelai_domain.models import DesignRevision
from jewelai_parser import (
    AmbiguousKnowledgeMatch,
    KnowledgeLibraryMatcher,
    KnowledgeMatchMethod,
    ResolvedKnowledgeMatch,
)
from jewelai_prompts import EnrichmentProposal, enrich_prompt, load_prompt_templates

ROOT = Path(__file__).resolve().parents[1]
RING = ROOT / "specs" / "jewelry-design-schema" / "fixtures" / "valid" / "ring.json"
PROMPTS = ROOT / "data" / "prompts" / "v1.0.0.json"


def _bundle() -> KnowledgeLibraryBundle:
    reviewed = Lifecycle.REVIEWED
    return KnowledgeLibraryBundle(
        contract_version="1.0.0",
        package_id="jewelai.regression.solitaire",
        artifact_version="1.0.0",
        sources=(
            Source(
                source_id="SRC-EVIDENCE",
                title="Synthetic reviewed regression evidence",
                source_type=SourceType.STANDARD,
                evidence_tier=EvidenceTier.PRIMARY,
                lifecycle_status=reviewed,
            ),
            Source(
                source_id="DEC-POLICY",
                title="Synthetic regression product policy",
                source_type=SourceType.INTERNAL_DECISION,
                evidence_tier=EvidenceTier.INTERNAL,
                lifecycle_status=reviewed,
            ),
        ),
        claims=(
            Claim(
                claim_id="CLM-OVAL",
                statement="Oval is a stone-shape concept in this regression fixture.",
                source_id="SRC-EVIDENCE",
                evidence_strength=EvidenceStrength.HIGH,
                lifecycle_status=reviewed,
            ),
            Claim(
                claim_id="CLM-ROUND",
                statement="Round is a stone-shape concept in this regression fixture.",
                source_id="SRC-EVIDENCE",
                evidence_strength=EvidenceStrength.HIGH,
                lifecycle_status=reviewed,
            ),
            Claim(
                claim_id="CLM-PRONG",
                statement="Prong is a setting concept in this regression fixture.",
                source_id="SRC-EVIDENCE",
                evidence_strength=EvidenceStrength.HIGH,
                lifecycle_status=reviewed,
            ),
            Claim(
                claim_id="CLM-BEZEL",
                statement="Bezel is a setting concept in this regression fixture.",
                source_id="SRC-EVIDENCE",
                evidence_strength=EvidenceStrength.HIGH,
                lifecycle_status=reviewed,
            ),
            Claim(
                claim_id="CLM-RED",
                statement="Red gold is distinct in this regression fixture.",
                source_id="SRC-EVIDENCE",
                evidence_strength=EvidenceStrength.HIGH,
                lifecycle_status=reviewed,
            ),
            Claim(
                claim_id="CLM-ROSE",
                statement="Rose gold is distinct in this regression fixture.",
                source_id="SRC-EVIDENCE",
                evidence_strength=EvidenceStrength.HIGH,
                lifecycle_status=reviewed,
            ),
            Claim(
                claim_id="CLM-SOLITAIRE",
                statement="Solitaire is a style concept in this regression fixture.",
                source_id="SRC-EVIDENCE",
                evidence_strength=EvidenceStrength.HIGH,
                lifecycle_status=reviewed,
            ),
            Claim(
                claim_id="CLM-ENGAGEMENT",
                statement="Engagement is an occasion concept in this regression fixture.",
                source_id="SRC-EVIDENCE",
                evidence_strength=EvidenceStrength.HIGH,
                lifecycle_status=reviewed,
            ),
        ),
        domain_knowledge=(
            DomainKnowledge(
                concept_id="occasion.engagement",
                kind="occasion",
                claim_ids=("CLM-ENGAGEMENT",),
                structural_schema=False,
                lifecycle_status=reviewed,
            ),
            DomainKnowledge(
                concept_id="setting.bezel",
                kind="setting",
                claim_ids=("CLM-BEZEL",),
                structural_schema=False,
                lifecycle_status=reviewed,
            ),
            DomainKnowledge(
                concept_id="setting.prong",
                kind="setting",
                claim_ids=("CLM-PRONG",),
                structural_schema=False,
                lifecycle_status=reviewed,
            ),
            DomainKnowledge(
                concept_id="stone.shape.oval",
                kind="stone_shape",
                claim_ids=("CLM-OVAL",),
                structural_schema=False,
                lifecycle_status=reviewed,
            ),
            DomainKnowledge(
                concept_id="stone.shape.round",
                kind="stone_shape",
                claim_ids=("CLM-ROUND",),
                structural_schema=False,
                lifecycle_status=reviewed,
            ),
            DomainKnowledge(
                concept_id="metal.color.red",
                kind="metal_color",
                claim_ids=("CLM-RED",),
                structural_schema=False,
                lifecycle_status=reviewed,
            ),
            DomainKnowledge(
                concept_id="metal.color.rose",
                kind="metal_color",
                claim_ids=("CLM-ROSE",),
                structural_schema=False,
                lifecycle_status=reviewed,
            ),
            DomainKnowledge(
                concept_id="style.solitaire",
                kind="style",
                claim_ids=("CLM-SOLITAIRE",),
                structural_schema=False,
                lifecycle_status=reviewed,
            ),
        ),
        language_mappings=(
            LanguageMapping(
                mapping_id="LANG-EN-OVAL",
                concept_id="stone.shape.oval",
                locale="en",
                canonical_term="oval",
                mapping_mode=MappingMode.DIRECT,
                mapping_quality=MappingQuality.EXACT,
                lifecycle_status=reviewed,
            ),
            LanguageMapping(
                mapping_id="LANG-EN-ROUND",
                concept_id="stone.shape.round",
                locale="en",
                canonical_term="round",
                mapping_mode=MappingMode.DIRECT,
                mapping_quality=MappingQuality.EXACT,
                lifecycle_status=reviewed,
            ),
            LanguageMapping(
                mapping_id="LANG-RU-OVAL",
                concept_id="stone.shape.oval",
                locale="ru",
                canonical_term="овал",
                aliases=("овальная",),
                mapping_mode=MappingMode.DIRECT,
                mapping_quality=MappingQuality.PREFERRED,
                lifecycle_status=reviewed,
            ),
            LanguageMapping(
                mapping_id="LANG-RU-PRONG",
                concept_id="setting.prong",
                locale="ru",
                canonical_term="крапановая закрепка",
                aliases=("крапановый",),
                mapping_mode=MappingMode.DIRECT,
                mapping_quality=MappingQuality.PREFERRED,
                lifecycle_status=reviewed,
            ),
            LanguageMapping(
                mapping_id="LANG-RU-BEZEL",
                concept_id="setting.bezel",
                locale="ru",
                canonical_term="глухая закрепка",
                mapping_mode=MappingMode.CONTEXTUAL,
                mapping_quality=MappingQuality.CONTEXT_DEPENDENT,
                context="stone_setting",
                lifecycle_status=reviewed,
            ),
            LanguageMapping(
                mapping_id="LANG-RU-RED",
                concept_id="metal.color.red",
                locale="ru",
                canonical_term="красное золото",
                mapping_mode=MappingMode.AMBIGUOUS,
                mapping_quality=MappingQuality.CONTEXT_DEPENDENT,
                lifecycle_status=reviewed,
            ),
            LanguageMapping(
                mapping_id="LANG-RU-ROSE",
                concept_id="metal.color.rose",
                locale="ru",
                canonical_term="красное золото",
                mapping_mode=MappingMode.AMBIGUOUS,
                mapping_quality=MappingQuality.CONTEXT_DEPENDENT,
                lifecycle_status=reviewed,
            ),
            LanguageMapping(
                mapping_id="LANG-RU-SOLITAIRE",
                concept_id="style.solitaire",
                locale="ru",
                canonical_term="солитер",
                mapping_mode=MappingMode.INPUT_ONLY,
                mapping_quality=MappingQuality.APPROXIMATE,
                lifecycle_status=reviewed,
            ),
            LanguageMapping(
                mapping_id="LANG-RU-ENGAGEMENT",
                concept_id="occasion.engagement",
                locale="ru",
                canonical_term="помолвочное кольцо",
                mapping_mode=MappingMode.DIRECT,
                mapping_quality=MappingQuality.PREFERRED,
                lifecycle_status=reviewed,
            ),
        ),
        policies=(
            Policy(
                policy_id="POL-SHAPE",
                target="center_stone.shape",
                effect="Preserve higher-precedence shape state.",
                source_kind="INTERNAL_PRODUCT_DECISION",
                source_refs=("DEC-POLICY",),
                lifecycle_status=reviewed,
            ),
            Policy(
                policy_id="POL-SETTING",
                target="center_stone.setting",
                effect="Allow explicit deterministic setting enrichment.",
                source_kind="INTERNAL_PRODUCT_DECISION",
                source_refs=("DEC-POLICY",),
                lifecycle_status=reviewed,
            ),
            Policy(
                policy_id="POL-METAL-COLOR",
                target="metal.color",
                effect="Preserve locked metal color.",
                source_kind="INTERNAL_PRODUCT_DECISION",
                source_refs=("DEC-POLICY",),
                lifecycle_status=reviewed,
            ),
            Policy(
                policy_id="POL-SIDE-SHAPE",
                target="side_stones.{group_id}.stones.shape",
                effect="Bind only existing stable side-stone groups.",
                source_kind="INTERNAL_PRODUCT_DECISION",
                source_refs=("DEC-POLICY",),
                lifecycle_status=reviewed,
            ),
        ),
    )


def _runtime():
    runtime, manifest = compile_knowledge_library(_bundle())
    return runtime, manifest


def _ring() -> DesignRevision:
    return DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))


def _templates():
    return load_prompt_templates(PROMPTS)


def test_compiler_runtime_identity_is_deterministic_and_never_active():
    first, first_manifest = _runtime()
    second, second_manifest = _runtime()

    assert first == second
    assert first.sha256 == second.sha256
    assert first_manifest == second_manifest
    assert first_manifest.runtime_sha256 == first.sha256
    assert first.active_for_production is False
    assert first_manifest.active_for_production is False


def test_ru_en_matcher_preserves_context_ambiguity_and_concept_boundaries():
    runtime, _ = _runtime()
    matcher = KnowledgeLibraryMatcher(runtime)

    en = matcher.match(" OVAL ", locale="en-US")
    assert isinstance(en, ResolvedKnowledgeMatch)
    assert en.candidate.concept_id == "stone.shape.oval"
    assert en.candidate.match_method == KnowledgeMatchMethod.EXACT

    ru = matcher.match("крапановой закрепки", locale="ru-RU")
    assert isinstance(ru, ResolvedKnowledgeMatch)
    assert ru.candidate.concept_id == "setting.prong"
    assert ru.candidate.match_method == KnowledgeMatchMethod.RU_MORPHOLOGY

    bezel = matcher.match("глухая закрепка", locale="ru")
    assert isinstance(bezel, AmbiguousKnowledgeMatch)
    assert bezel.reason == "context_required"

    bezel_with_context = matcher.match(
        "глухая закрепка",
        locale="ru",
        context="stone_setting",
    )
    assert isinstance(bezel_with_context, ResolvedKnowledgeMatch)
    assert bezel_with_context.candidate.concept_id == "setting.bezel"

    red_gold = matcher.match("красное золото", locale="ru")
    assert isinstance(red_gold, AmbiguousKnowledgeMatch)
    assert red_gold.reason == "declared_ambiguous"
    assert {item.concept_id for item in red_gold.candidates} == {
        "metal.color.red",
        "metal.color.rose",
    }

    engagement = matcher.match("помолвочное кольцо", locale="ru")
    solitaire = matcher.match("солитер", locale="ru")
    assert isinstance(engagement, ResolvedKnowledgeMatch)
    assert isinstance(solitaire, ResolvedKnowledgeMatch)
    assert engagement.candidate.concept_id == "occasion.engagement"
    assert solitaire.candidate.concept_id == "style.solitaire"


def test_runtime_projection_does_not_silently_infer_cut_dimensions_or_material():
    runtime, _ = _runtime()
    ring = json.loads(RING.read_text(encoding="utf-8"))
    ring["design"]["center_stone"]["shape"]["value"] = "round"
    ring["design"]["center_stone"]["material"] = None
    revision = DesignRevision.model_validate(ring)

    state = build_knowledge_runtime_state(runtime, revision)

    assert state.get("center_stone.shape").value == "round"
    assert state.get("center_stone.cut").semantic_state == RuntimeSemanticState.MISSING
    assert state.get("center_stone.weight").value == {"value": 3.0, "unit": "ct"}
    assert state.get("center_stone.dimensions").semantic_state == RuntimeSemanticState.MISSING
    assert state.get("center_stone.material").semantic_state == RuntimeSemanticState.MISSING


def test_enrichment_precedence_locked_state_and_collection_binding_regression():
    runtime, _ = _runtime()
    result = enrich_prompt(
        _ring(),
        _templates(),
        runtime,
        proposals=(
            EnrichmentProposal(
                target="center_stone.setting",
                semantic_state=RuntimeSemanticState.RECOMMENDED,
                provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
                value="prong_setting",
                source_id="REG-SETTING",
            ),
            EnrichmentProposal(
                target="center_stone.shape",
                semantic_state=RuntimeSemanticState.RECOMMENDED,
                provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
                value="round",
                source_id="REG-SHAPE",
            ),
            EnrichmentProposal(
                target="metal.color",
                semantic_state=RuntimeSemanticState.NORMALIZED,
                provenance=RuntimeProvenance.USER_CONFIRMED,
                value="yellow",
                source_id="REG-METAL",
            ),
            EnrichmentProposal(
                target="side_stones.accents.stones.shape",
                semantic_state=RuntimeSemanticState.NORMALIZED,
                provenance=RuntimeProvenance.USER_CONFIRMED,
                value="marquise",
                source_id="REG-SIDE",
            ),
            EnrichmentProposal(
                target="side_stones.unknown.stones.shape",
                semantic_state=RuntimeSemanticState.NORMALIZED,
                provenance=RuntimeProvenance.USER_CONFIRMED,
                value="marquise",
                source_id="REG-UNKNOWN",
            ),
        ),
    )
    decisions = {item.target: item for item in result.decisions}

    assert decisions["center_stone.setting"].outcome == "APPLIED"
    assert decisions["center_stone.setting"].result.value == "prong_setting"
    assert decisions["center_stone.shape"].outcome == "KEPT"
    assert decisions["center_stone.shape"].reason == "lower_precedence"
    assert decisions["center_stone.shape"].result.value == "oval"
    assert decisions["metal.color"].outcome == "BLOCKED"
    assert decisions["metal.color"].reason == "locked"
    assert decisions["metal.color"].result.value == "white"
    assert decisions["side_stones.accents.stones.shape"].outcome == "APPLIED"
    assert decisions["side_stones.unknown.stones.shape"].outcome == "BLOCKED"
    assert decisions["side_stones.unknown.stones.shape"].reason == "unknown_target"


def test_enrichment_is_derived_state_and_cannot_silently_rewrite_prompt():
    runtime, _ = _runtime()
    ring = _ring()
    templates = _templates()
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
                source_id="REG-PROMPT",
            ),
        ),
    )

    final = {item.target: item for item in enriched.final_matrix}
    assert final["center_stone.setting"].value == "prong_setting"
    assert enriched.compiled_prompt == baseline.compiled_prompt
    assert enriched.design_revision_id == str(ring.revision_id)
    assert enriched.knowledge_runtime_sha256 == runtime.sha256
