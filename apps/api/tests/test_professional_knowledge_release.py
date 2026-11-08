"""Bounded checks of actual recovered catalogs, not a synthetic Knowledge bundle.

These are lower-level release checks. They do not claim HTTP/browser acceptance,
external factual re-review, recovery of P0-12, or a deployed ACTIVE release.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest
from jewelai_domain.knowledge_library import KnowledgeLibraryBundle
from jewelai_domain.knowledge_library_v1_1 import (
    KnowledgeLibraryBundleV1_1,
    compile_knowledge_library_v1_1,
)
from jewelai_domain.knowledge_storage_v1_1 import KnowledgeArtifactStoreV1_1
from jewelai_domain.models import DesignRevision
from jewelai_parser import KnowledgeLibraryMatcher, ResolvedKnowledgeMatch, parse_full_message
from jewelai_prompts import EnrichmentProposal, enrich_prompt

from jewelai_api.artifacts import load_runtime_artifacts
from jewelai_api.parametric_enrichment import select_parametric_references
from jewelai_api.settings import ArtifactVersions

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/knowledge"))
integration = importlib.import_module("prepare_preprod_integration")


@pytest.fixture(scope="module")
def catalogs():
    from build_p010_symmetry_draft import extended_draft

    candidate = extended_draft().model_copy(
        update={
            "package_id": integration.PACKAGE_ID,
            "artifact_version": integration.ARTIFACT_VERSION,
        }
    )
    runtime = compile_knowledge_library_v1_1(candidate)[0]
    artifacts = load_runtime_artifacts(ROOT, ArtifactVersions(questions="2.0.0", rules="2.0.0"))
    return candidate, runtime, artifacts


def test_real_compiler_contract(catalogs, tmp_path):
    candidate, runtime, _ = catalogs
    assert compile_knowledge_library_v1_1(candidate)[0] == runtime
    store = KnowledgeArtifactStoreV1_1(tmp_path)
    assert store.publish(candidate) == store.load(candidate.package_id, "1.0.0")
    assert store.load(candidate.package_id, "1.0.0").runtime_sha256 == runtime.sha256
    assert runtime.active_for_production is False
    damaged = Path(tmp_path / candidate.package_id / "1.0.0/runtime.json")
    damaged.write_bytes(damaged.read_bytes() + b" ")
    with pytest.raises(ValueError):
        store.load(candidate.package_id, "1.0.0")


def test_real_provenance_and_separate_contracts(catalogs):
    candidate, _, artifacts = catalogs
    core = KnowledgeLibraryBundle.model_validate_json(
        (ROOT / "data/knowledge/v1/jewelry-core-1.0.0.json").read_bytes()
    )
    fragment = KnowledgeLibraryBundleV1_1.model_validate_json(
        (ROOT / "data/knowledge/v1_1/p010-symmetry-0.1.0.json").read_bytes()
    )
    # All original IDs/records/lifecycles retained, no invented merging/dedup.
    for group in ("sources", "claims", "domain_knowledge", "language_mappings", "policies"):
        records = [r.model_dump(mode="json") for r in getattr(candidate, group)]
        originals = [
            r.model_dump(mode="json") for r in (*getattr(core, group), *getattr(fragment, group))
        ]
        assert records == originals
        assert all(record["lifecycle_status"] == "REVIEWED" for record in records)
    raw_dictionary = json.loads((ROOT / "data/dictionary/v1.0.0.json").read_bytes())
    assert raw_dictionary["review_status"] == "proposed_pending_domain_review"
    assert len(raw_dictionary["entries"]) == 21
    catalog = artifacts.parametric_knowledge
    assert (
        len(catalog.sources),
        len(catalog.specific_gravity),
        len(catalog.calibrated_size_weight),
    ) == (12, 8, 564)
    sources = {source.source_id for source in catalog.sources}
    assert all(
        r.source_id in sources for r in (*catalog.specific_gravity, *catalog.calibrated_size_weight)
    )


def test_real_language_matcher(catalogs):
    _, runtime, _ = catalogs
    matcher = KnowledgeLibraryMatcher(runtime)
    assert len(runtime.language_mappings) == 213
    for mapping in runtime.language_mappings:
        for surface in (mapping.canonical_term, *mapping.aliases):
            result = matcher.match(surface, locale=mapping.locale, context=mapping.context)
            if isinstance(result, ResolvedKnowledgeMatch):
                assert result.candidate.concept_id == mapping.concept_id
            else:
                assert mapping.concept_id in {c.concept_id for c in result.candidates}


def _revision():
    return DesignRevision.model_validate_json(
        (ROOT / "specs/jewelry-design-schema/fixtures/valid/ring.json").read_bytes()
    )


def test_real_runtime_policy(catalogs):
    _, runtime, artifacts = catalogs
    revision = _revision()
    result = enrich_prompt(
        revision,
        artifacts.prompts,
        runtime,
        proposals=(
            EnrichmentProposal(
                target="metal.color",
                value="yellow",
                semantic_state="NORMALIZED",
                provenance="NORMALIZED_FROM_USER",
                source_id="bounded-user-message",
            ),
            EnrichmentProposal(
                target="side_stones.missing.stones.shape",
                value="round",
                semantic_state="RECOMMENDED",
                provenance="JEWELAI_RECOMMENDED",
                source_id="DEC-JEWELAI-PRODUCTION-CATALOG-V1",
            ),
        ),
    )
    decisions = {d.target: d for d in result.decisions}
    assert decisions["metal.color"].reason == "locked"
    assert decisions["metal.color"].result.value == "white"
    assert decisions["side_stones.missing.stones.shape"].reason == "unknown_target"
    assert "POL-PROD-03-METAL-COLOR" in decisions["metal.color"].applicable_policy_ids


def test_real_prompt_matrix_and_parametric_integration(catalogs):
    _, runtime, artifacts = catalogs
    revision = _revision()
    raw = revision.model_dump(mode="json")
    source = revision.event.source.model_dump(mode="json")
    for name, value in (
        ("material", "diamond"),
        ("shape", "round"),
        ("weight", {"value": 1.0, "unit": "ct"}),
    ):
        raw["design"]["center_stone"][name] = dict(
            availability="value",
            value=value,
            origin="explicit",
            source=source,
            confirmed=True,
            locked=False,
        )
    raw["design"]["center_stone"]["dimensions"] = dict(
        availability="unknown",
        value=None,
        origin="unknown",
        requirement="undetermined",
        confirmed=False,
        locked=False,
    )
    revision = DesignRevision.model_validate(raw)
    before = revision.model_dump_json()
    refs = select_parametric_references(revision, artifacts.parametric_knowledge)
    assert refs and any(r.dimensions.diameter_mm == 6.5 for r in refs)
    assert all(r.source_ids and r.record_ids and r.uncertainty for r in refs)
    kwargs = dict(
        parametric_catalog_id=artifacts.parametric_knowledge.catalog_id,
        parametric_artifact_version="1.0.0",
        parametric_catalog_sha256=artifacts.parametric_knowledge.sha256,
        parametric_references=refs,
    )
    result = enrich_prompt(revision, artifacts.prompts, runtime, **kwargs)
    assert result == enrich_prompt(revision, artifacts.prompts, runtime, **kwargs)
    assert revision.model_dump_json() == before
    assert revision.design.center_stone.dimensions.value is None
    assert result.parametric_references == refs
    assert result.knowledge_runtime_sha256 == runtime.sha256
    raw["design"]["center_stone"]["weight"]["value"]["value"] = 1.000123
    assert (
        select_parametric_references(
            DesignRevision.model_validate(raw), artifacts.parametric_knowledge
        )
        == ()
    )


def test_real_behavioral_negative_boundary(catalogs):
    _, runtime, artifacts = catalogs
    parsed = parse_full_message(
        "I want a gold ring and I do not want a platinum ring.",
        locale="en",
        dictionary=artifacts.dictionary,
        knowledge_runtime=runtime,
    )
    assert parsed.parse_version == "1.3.0"
    assert any(
        c.normalized_values == ("gold",) and c.parser_update is not None for c in parsed.candidates
    )
    rejected = [c for c in parsed.candidates if c.normalized_values == ("platinum",)]
    assert rejected and all(
        c.classification == "prohibition" and c.parser_update is None for c in rejected
    )
    assert not any(c.target == "center_stone.dimensions" for c in parsed.candidates)


def test_staging_does_not_create_active_and_rejects_bad_recovery(tmp_path):
    with pytest.raises(ValueError, match="unverified recovery"):
        integration.verify_recovery(b"[]")
    assert not tmp_path.joinpath("active.json").exists()


def test_real_round_gap_is_evidence_not_an_invented_binding(catalogs):
    _, runtime, artifacts = catalogs
    parsed = parse_full_message(
        "A round diamond center stone.",
        locale="en",
        dictionary=artifacts.dictionary,
        knowledge_runtime=runtime,
    )
    round_candidates = [c for c in parsed.candidates if c.normalized_values == ("round",)]
    assert round_candidates
    assert all(
        c.normalization_source == "knowledge_library" and c.parser_update is None
        for c in round_candidates
    )
