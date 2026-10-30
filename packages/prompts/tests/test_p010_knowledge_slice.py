import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from jewelai_domain.knowledge_library_v1_1 import compile_knowledge_library_v1_1
from jewelai_domain.knowledge_qualification_v1_1 import qualify_knowledge_release_v1_1
from jewelai_domain.knowledge_storage_v1_1 import KnowledgeArtifactStoreV1_1
from jewelai_domain.models import DesignRevision
from jewelai_domain.models_v1_1 import upgrade_design_revision_v1_to_v1_1

from jewelai_prompts import EnrichmentProposal, enrich_prompt, load_prompt_templates

ROOT = Path(__file__).resolve().parents[3]
DIRECTORY = ROOT / "data/knowledge/v1_1"


@pytest.fixture
def c2_packaging(monkeypatch):
    from test_recovered_knowledge_draft import packaging

    monkeypatch.setitem(sys.modules, "build_recovered_draft", packaging)
    spec = importlib.util.spec_from_file_location(
        "p010_draft", ROOT / "tools/knowledge/build_p010_symmetry_draft.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_p010_authentic_slice_preserves_approved_statements_ids_and_pointers():
    bundle = json.loads((DIRECTORY / "p010-symmetry-0.1.0.json").read_bytes())
    provenance = json.loads((DIRECTORY / "p010-symmetry-provenance-0.1.0.json").read_bytes())
    records = {
        r[identity]: r
        for group, identity in [
            ("sources", "source_id"),
            ("claims", "claim_id"),
            ("domain_knowledge", "concept_id"),
            ("language_mappings", "mapping_id"),
            ("policies", "policy_id"),
        ]
        for r in bundle[group]
    }
    assert len(records) == 10
    assert len(provenance["records"]) == 10
    for row in provenance["records"]:
        record = records[row["record_id"]]
        digest = hashlib.sha256(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        assert digest == row["record_sha256"]
    assert (
        records["CLM-P010-C2-ASYMMETRY"]["statement"]
        == provenance["original_excerpts"]["/composition_primitives/1"]["definition"]
    )
    assert (
        records["CLM-P010-C2-T10-10"]["statement"]
        == provenance["original_excerpts"]["/mini_tests/9"]["expected"]
    )
    for index in [1, 5, 6]:
        original = provenance["original_excerpts"][f"/style_cue_policy/{index}"]
        assert records[original["rule_id"]]["effect"] == original["rule"]
        assert records[original["rule_id"]]["target"] == "composition.symmetry_mode"
    assert "geometric" not in records
    runtime, manifest = compile_knowledge_library_v1_1(bundle)
    assert runtime.sha256 == manifest.runtime_sha256
    assert runtime == compile_knowledge_library_v1_1(bundle)[0]
    assert runtime.active_for_production is False


def test_actual_extended_draft_compiles_enriches_and_stays_unqualified(tmp_path, c2_packaging):
    # No synthetic report/ACTIVE is created for this actual DRAFT identity.
    payload = c2_packaging.extended_draft().model_dump(mode="json")
    runtime, _ = compile_knowledge_library_v1_1(payload)
    store = KnowledgeArtifactStoreV1_1(tmp_path)
    stored = store.publish(payload)
    assert store.load(runtime.package_id, "0.2.0").runtime_sha256 == runtime.sha256
    assert store.publish(payload) == stored
    revision = upgrade_design_revision_v1_to_v1_1(
        DesignRevision.model_validate_json(
            (ROOT / "specs/jewelry-design-schema/fixtures/valid/ring.json").read_bytes()
        )
    )
    before = revision.model_dump_json()
    result = enrich_prompt(
        revision,
        load_prompt_templates(ROOT / "data/prompts/v1.0.0.json"),
        runtime,
        proposals=(
            EnrichmentProposal(
                target="composition",
                semantic_state="NORMALIZED",
                provenance="NORMALIZED_FROM_USER",
                value={
                    "symmetry_mode": {
                        "availability": "value",
                        "origin": "explicit",
                        "value": "asymmetrical",
                        "source": revision.event.source.model_dump(mode="json"),
                        "confirmed": False,
                        "locked": False,
                    },
                    "organization": None,
                    "focal_hierarchy": None,
                    "negative_space_intent": None,
                    "rhythm": None,
                },
                source_id="candidate_t10_10",
            ),
        ),
    )
    assert result.decisions[0].outcome == "APPLIED"
    assert revision.model_dump_json() == before
    qualification = qualify_knowledge_release_v1_1(
        store, {"package_id": runtime.package_id, "artifact_version": "0.2.0"}
    )
    assert (
        qualification.status == "BLOCKED"
        and qualification.blockers[0].code == "active_envelope_missing"
    )
    staged = c2_packaging.build(tmp_path / "isolated-draft")
    assert staged["runtime_sha256"] == runtime.sha256
    assert staged["status"] == "DRAFT_NOT_ACTIVE_NOT_QUALIFIED"
    with pytest.raises(ValueError, match="new isolated directory"):
        c2_packaging.build(tmp_path / "isolated-draft")


@pytest.mark.parametrize(
    "group", ["sources", "claims", "domain_knowledge", "language_mappings", "policies"]
)
def test_c2_packager_rejects_collisions_in_every_record_group(c2_packaging, monkeypatch, group):
    base = c2_packaging.project_core(c2_packaging.SOURCE.read_bytes()).model_dump(mode="json")
    fragment = json.loads((DIRECTORY / "p010-symmetry-0.1.0.json").read_bytes())
    identity = c2_packaging.RECORD_GROUPS[group]
    # Simulate a conflicting future core identity, never publish this hostile input.
    base[group][0][identity] = fragment[group][0][identity]
    monkeypatch.setattr(
        c2_packaging, "project_core", lambda _: SimpleNamespace(model_dump=lambda **_: base)
    )
    with pytest.raises(ValueError, match=f"{group} identity collision"):
        c2_packaging.extended_draft()
