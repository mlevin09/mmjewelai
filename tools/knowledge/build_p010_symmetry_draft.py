"""Reproducible C2 extension of recovered-core, isolated DRAFT staging only."""

import argparse
import json
from pathlib import Path

from build_recovered_draft import RECORD_GROUPS, ROOT, SOURCE, project_core
from jewelai_domain.knowledge_library_v1_1 import (
    KnowledgeLibraryBundleV1_1,
    compile_knowledge_library_v1_1,
)
from jewelai_domain.knowledge_storage_v1_1 import KnowledgeArtifactStoreV1_1


def extended_draft():
    base = project_core(SOURCE.read_bytes()).model_dump(mode="json")
    fragment = KnowledgeLibraryBundleV1_1.model_validate_json(
        (ROOT / "data/knowledge/v1_1/p010-symmetry-0.1.0.json").read_bytes()
    ).model_dump(mode="json")
    for group, key in RECORD_GROUPS.items():
        before = {record[key] for record in base[group]}
        incoming = {record[key] for record in fragment[group]}
        if before & incoming or len(incoming) != len(fragment[group]):
            raise ValueError(f"P0-10 {group} identity collision; no overwrite allowed")
        base[group].extend(fragment[group])
    base["artifact_version"] = "0.2.0"
    candidate = KnowledgeLibraryBundleV1_1.model_validate(base)
    compile_knowledge_library_v1_1(candidate)
    return candidate


def build(output: Path):
    if output.exists():
        raise ValueError("C2 DRAFT output must be a new isolated directory")
    candidate = extended_draft()
    stored = KnowledgeArtifactStoreV1_1(output).publish(candidate)
    return {
        "status": "DRAFT_NOT_ACTIVE_NOT_QUALIFIED",
        "package_id": stored.package_id,
        "artifact_version": stored.artifact_version,
        "source_sha256": stored.source_sha256,
        "runtime_sha256": stored.runtime_sha256,
        "manifest_sha256": stored.manifest_sha256,
        "qualification_evidence": "NOT_CREATED; existing real release gaps remain",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(build(parser.parse_args().output), indent=2))
