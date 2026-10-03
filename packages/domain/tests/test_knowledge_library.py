import copy
import hashlib
import json

import pytest
from pydantic import ValidationError

from jewelai_domain.knowledge_library import (
    KnowledgeLibraryValidationError,
    compile_knowledge_library,
    validate_knowledge_library,
)


def bundle():
    return {
        "contract_version": "1.0.0",
        "package_id": "jewelai.test.solitaire",
        "artifact_version": "0.3.0",
        "sources": [
            {
                "source_id": "SRC-1",
                "title": "Reviewed source",
                "source_type": "OFFICIAL_BODY",
                "evidence_tier": "PRIMARY",
                "lifecycle_status": "REVIEWED",
                "language": "en",
            },
            {
                "source_id": "SRC-DRAFT",
                "title": "Draft source",
                "source_type": "RETAIL_SECONDARY",
                "evidence_tier": "SECONDARY",
                "lifecycle_status": "DRAFT",
                "language": "ru",
            },
            {
                "source_id": "DEC-1",
                "title": "Internal product decision",
                "source_type": "INTERNAL_DECISION",
                "evidence_tier": "INTERNAL",
                "lifecycle_status": "REVIEWED",
                "language": "not_applicable",
            },
        ],
        "claims": [
            {
                "claim_id": "CLM-1",
                "statement": "A reviewed claim.",
                "source_id": "SRC-1",
                "supporting_source_ids": [],
                "evidence_strength": "HIGH",
                "lifecycle_status": "REVIEWED",
            },
            {
                "claim_id": "CLM-DRAFT",
                "statement": "A draft claim.",
                "source_id": "SRC-DRAFT",
                "evidence_strength": "LOW",
                "lifecycle_status": "DRAFT",
            },
        ],
        "domain_knowledge": [
            {
                "concept_id": "stone.shape",
                "kind": "taxonomy",
                "claim_ids": [],
                "structural_schema": True,
                "lifecycle_status": "REVIEWED",
            },
            {
                "concept_id": "stone.shape.oval",
                "kind": "shape",
                "parent_id": "stone.shape",
                "claim_ids": ["CLM-1"],
                "structural_schema": False,
                "lifecycle_status": "REVIEWED",
            },
            {
                "concept_id": "stone.shape.draft",
                "kind": "shape",
                "parent_id": "stone.shape",
                "claim_ids": ["CLM-DRAFT"],
                "structural_schema": False,
                "lifecycle_status": "DRAFT",
            },
        ],
        "language_mappings": [
            {
                "mapping_id": "LANG-EN-OVAL",
                "concept_id": "stone.shape.oval",
                "locale": "en",
                "canonical_term": "oval",
                "aliases": [],
                "mapping_mode": "DIRECT",
                "mapping_quality": "EXACT",
                "lifecycle_status": "REVIEWED",
            },
            {
                "mapping_id": "LANG-RU-OVAL",
                "concept_id": "stone.shape.oval",
                "locale": "ru",
                "canonical_term": "овал",
                "aliases": ["овальная"],
                "mapping_mode": "DIRECT",
                "mapping_quality": "PREFERRED",
                "lifecycle_status": "REVIEWED",
            },
        ],
        "policies": [
            {
                "policy_id": "POL-1",
                "target": "center_stone.shape",
                "effect": "Normalize an explicit oval shape without inferring cutting style.",
                "source_kind": "DOMAIN_KNOWLEDGE",
                "source_refs": ["stone.shape.oval"],
                "lifecycle_status": "REVIEWED",
            },
            {
                "policy_id": "POL-2",
                "target": "side_stones.{group_id}.stones.shape",
                "effect": "Address only an existing stable side-stone group.",
                "source_kind": "INTERNAL_PRODUCT_DECISION",
                "source_refs": ["DEC-1"],
                "lifecycle_status": "REVIEWED",
            },
        ],
    }


def test_compiler_is_deterministic_and_never_active():
    first_runtime, first_manifest = compile_knowledge_library(bundle())
    second_runtime, second_manifest = compile_knowledge_library(bundle())

    assert first_runtime == second_runtime
    assert first_manifest == second_manifest
    assert first_runtime.active_for_production is False
    assert {item.lifecycle_status for item in first_runtime.sources} == {"COMPILED"}
    assert {item.lifecycle_status for item in first_runtime.claims} == {"COMPILED"}
    assert {item.lifecycle_status for item in first_runtime.domain_knowledge} == {"COMPILED"}
    assert {item.lifecycle_status for item in first_runtime.language_mappings} == {"COMPILED"}
    assert {item.lifecycle_status for item in first_runtime.policies} == {"COMPILED"}
    assert "SRC-DRAFT" not in {item.source_id for item in first_runtime.sources}
    assert "CLM-DRAFT" not in {item.claim_id for item in first_runtime.claims}

    digest = hashlib.sha256(first_runtime.canonical_json().encode()).hexdigest()
    assert first_manifest.runtime_sha256 == digest


def test_compiler_sorts_semantically_unordered_inputs():
    original = bundle()
    reordered = copy.deepcopy(original)
    for key in ("sources", "claims", "domain_knowledge", "language_mappings", "policies"):
        reordered[key].reverse()

    original_runtime, original_manifest = compile_knowledge_library(original)
    reordered_runtime, reordered_manifest = compile_knowledge_library(reordered)
    assert original_runtime.canonical_json() == reordered_runtime.canonical_json()
    assert original_manifest == reordered_manifest


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda data: data["claims"][0].update(source_id="MISSING"),
            "unknown source",
        ),
        (
            lambda data: data["domain_knowledge"][1].update(parent_id="missing.parent"),
            "unknown parent",
        ),
        (
            lambda data: data["language_mappings"][0].update(concept_id="missing.concept"),
            "unknown concept",
        ),
        (
            lambda data: data["policies"][0].update(target="center_stone.prong_count"),
            "unavailable Design Schema",
        ),
    ],
)
def test_validator_fails_closed_on_broken_references_and_targets(mutate, match):
    data = bundle()
    mutate(data)
    with pytest.raises(KnowledgeLibraryValidationError, match=match):
        validate_knowledge_library(data)


def test_validator_rejects_array_index_collection_target():
    data = bundle()
    data["policies"][1]["target"] = "side_stones.0.stones.shape"
    with pytest.raises(ValidationError, match="String should match pattern"):
        validate_knowledge_library(data)


def test_validator_rejects_direct_ambiguous_collision():
    data = bundle()
    data["language_mappings"].append(
        {
            "mapping_id": "LANG-EN-OVAL-AMB",
            "concept_id": "stone.shape.oval",
            "locale": "en",
            "canonical_term": " OVAL ",
            "mapping_mode": "AMBIGUOUS",
            "mapping_quality": "CONTEXT_DEPENDENT",
            "lifecycle_status": "DRAFT",
        }
    )
    with pytest.raises(KnowledgeLibraryValidationError, match="DIRECT/AMBIGUOUS collision"):
        validate_knowledge_library(data)


def test_validator_rejects_reviewed_dependency_on_draft():
    data = bundle()
    data["domain_knowledge"][2]["lifecycle_status"] = "REVIEWED"
    with pytest.raises(KnowledgeLibraryValidationError, match="non-REVIEWED claim"):
        compile_knowledge_library(data)


@pytest.mark.parametrize("status", ["COMPILED", "ACTIVE"])
def test_validator_rejects_runtime_lifecycle_as_source_input(status):
    data = bundle()
    data["sources"][0]["lifecycle_status"] = status
    with pytest.raises(KnowledgeLibraryValidationError, match="runtime lifecycle"):
        validate_knowledge_library(data)


def test_exact_contract_and_artifact_version_are_required():
    data = bundle()
    data["contract_version"] = "1.1.0"
    with pytest.raises(ValidationError):
        validate_knowledge_library(data)

    data = bundle()
    data.pop("artifact_version")
    registry = validate_knowledge_library(data)
    with pytest.raises(KnowledgeLibraryValidationError, match="artifact_version"):
        registry.compile()


def test_primary_source_cannot_be_repeated_as_supporting_source():
    data = bundle()
    data["claims"][0]["supporting_source_ids"] = ["SRC-1"]
    with pytest.raises(ValidationError, match="primary source"):
        validate_knowledge_library(data)


def test_runtime_json_is_stable_utf8_json():
    runtime, _ = compile_knowledge_library(bundle())
    payload = runtime.canonical_json()
    assert json.loads(payload)["contract_version"] == "1.0.0"
    assert "\\u043e" not in payload
