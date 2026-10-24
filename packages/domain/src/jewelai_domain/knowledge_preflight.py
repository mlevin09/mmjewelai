"""Read-only Knowledge Library release qualification command."""

import argparse
import json
from pathlib import Path

from .knowledge_qualification import (
    KnowledgeReleaseCandidateSelection,
    KnowledgeReleaseQualificationStatus,
    qualify_knowledge_release,
)
from .knowledge_storage import KnowledgeArtifactStore


def _json_file(path: str | None) -> object | None:
    if path is None:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"invalid_evidence": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--package-id")
    parser.add_argument("--artifact-version")
    parser.add_argument("--active-release")
    parser.add_argument("--validation-report")
    parser.add_argument(
        "--candidate-kind",
        choices=("PRODUCTION_INTENDED", "SYNTHETIC"),
        default="PRODUCTION_INTENDED",
    )
    parser.add_argument("--source-commit")
    args = parser.parse_args()

    if (args.package_id is None) != (args.artifact_version is None):
        parser.error("--package-id and --artifact-version must be supplied together")

    selection = None
    if args.package_id is not None:
        selection = KnowledgeReleaseCandidateSelection(
            package_id=args.package_id,
            artifact_version=args.artifact_version,
            kind=args.candidate_kind,
        )
    result = qualify_knowledge_release(
        KnowledgeArtifactStore(args.artifact_root),
        selection,
        active_release=_json_file(args.active_release),
        validation_report=_json_file(args.validation_report),
        source_commit=args.source_commit,
    )
    print(result.canonical_json())
    return {
        KnowledgeReleaseQualificationStatus.QUALIFIED: 0,
        KnowledgeReleaseQualificationStatus.BLOCKED: 1,
        KnowledgeReleaseQualificationStatus.NOT_EVALUATED: 2,
    }[result.status]


if __name__ == "__main__":
    raise SystemExit(main())
