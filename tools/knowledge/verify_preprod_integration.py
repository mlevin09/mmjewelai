"""Read-only verification of the staged release against actual container data."""

import argparse
import hashlib
import json
from pathlib import Path

from jewelai_api.artifacts import load_runtime_artifacts
from jewelai_api.settings import ArtifactVersions
from jewelai_domain.knowledge_activation_v1_1 import ProductionValidationReportV1_1
from jewelai_domain.knowledge_qualification_v1_1 import qualify_knowledge_release_v1_1
from jewelai_domain.knowledge_storage_v1_1 import KnowledgeArtifactStoreV1_1


def verify(release_root: Path, repository_root: Path):
    manifest = json.loads((release_root / "integration-manifest.json").read_bytes())
    semantic = manifest["semantic"]
    report = ProductionValidationReportV1_1.model_validate_json(
        (release_root / "validation-report.json").read_bytes()
    )
    qualification = qualify_knowledge_release_v1_1(
        KnowledgeArtifactStoreV1_1(release_root / "knowledge"),
        {
            "package_id": semantic["package_id"],
            "artifact_version": semantic["artifact_version"],
            "kind": "PRODUCTION_INTENDED",
        },
        active_release=json.loads((release_root / "active.json").read_bytes()),
        validation_report=report,
    )
    if (
        qualification.status != "QUALIFIED"
        or qualification.runtime_sha256 != semantic["runtime_sha256"]
        or report.sha256 != semantic["production_validation_report_sha256"]
        or semantic["contract_version"] != "1.1.0"
    ):
        raise ValueError("Professional Knowledge release verification failed")
    artifacts = load_runtime_artifacts(repository_root, ArtifactVersions(**manifest["versions"]))
    actual = [dict(name=k, file_sha256=v) for k, v in artifacts.artifact_hashes]
    if actual != manifest["consumer_artifacts"]:
        raise ValueError("Consumer artifact bytes do not match the integration manifest")
    if artifacts.parametric_knowledge.sha256 != manifest["parametric"]["typed_runtime_sha256"]:
        raise ValueError("Parametric runtime identity mismatch")
    # Never interpret caller-controlled paths from a manifest as filesystem authority.
    paths = {
        "semantic_core": "data/knowledge/v1/jewelry-core-1.0.0.json",
        "parametric": "data/knowledge-base/v1.0.0.json",
        "dictionary": "data/dictionary/v1.0.0.json",
    }
    for component, relative in paths.items():
        identity = manifest["recovered_components"][component]
        if (
            identity["path"] != relative
            or hashlib.sha256((repository_root / relative).read_bytes()).hexdigest()
            != identity["file_sha256"]
        ):
            raise ValueError("Recovered component identity mismatch")
    return qualification


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_root", type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path("/app"))
    args = parser.parse_args()
    print(verify(args.release_root, args.repository_root).canonical_json())
