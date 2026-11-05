"""Stage recovered text-only Knowledge components without merging their contracts.

This operational manifest is not a public/session DTO. Staging never manufactures
validation evidence or activates a release. Promotion requires a separately
supplied, exact-runtime, all-PASS report through the existing ADR 0028 gate.
"""

import argparse
import hashlib
import json
from pathlib import Path

from build_p010_symmetry_draft import extended_draft
from build_recovered_draft import RECOVERY_SHA256, ROOT, canonical, require
from jewelai_api.artifacts import load_runtime_artifacts
from jewelai_api.settings import ArtifactVersions
from jewelai_domain.knowledge_activation_v1_1 import (
    ProductionValidationReportV1_1,
    promote_knowledge_runtime_v1_1,
)
from jewelai_domain.knowledge_library_v1_1 import compile_knowledge_library_v1_1
from jewelai_domain.knowledge_storage_v1_1 import KnowledgeArtifactStoreV1_1

RECOVERED_COMPONENTS = {
    "semantic_core": ("data/knowledge/v1/jewelry-core-1.0.0.json", 382),
    "parametric": ("data/knowledge-base/v1.0.0.json", 584),
    "dictionary": ("data/dictionary/v1.0.0.json", 21),
}
PACKAGE_ID = "jewelai.preprod.recovered_core"
ARTIFACT_VERSION = "1.0.0"
BOUNDED_GAPS = (
    {
        "original": "round / LANG-EN-ROUND",
        "component": "Existing Knowledge concept; absent executable Dictionary entry",
        "text_only_blocker": "Round-specific canonical intake; not oval/other supported paths",
        "replacement": None,
        "status": "Recognized evidence only; no new Dictionary approval or binding invented",
    },
    {
        "original": "P0-12 original 50 visual/structural error-class definitions",
        "component": "Visualization Verification, not Dictionary",
        "text_only_blocker": False,
        "replacement": None,
        "status": "ORIGINAL_NOT_RECOVERED; no taxonomy invented",
    },
    {
        "original": "P0-10 mappings beyond the approved T10-10 symmetry slice",
        "component": "Semantic Knowledge policies",
        "text_only_blocker": False,
        "replacement": None,
        "status": "Not executable; unsupported intent remains evidence",
    },
    {
        "original": "Unenumerated historical approximately 50 missing words",
        "component": "UNKNOWN; not equated with P0-12 classes",
        "text_only_blocker": False,
        "replacement": None,
        "status": "No exact word inventory found; no translations invented",
    },
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify_recovery(recovery_bytes, *, root=ROOT):
    """Verify every original record in all three contracts, not just core."""
    require(digest(recovery_bytes) == RECOVERY_SHA256, "unverified recovery register")
    rows = json.loads(recovery_bytes)
    receipts = {}
    for component, (name, count) in RECOVERED_COMPONENTS.items():
        raw = (root / name).read_bytes()
        payload = json.loads(raw)
        original = [row for row in rows if row.get("file") == name]
        require(len(original) == count, "incomplete recovered component")
        seen = set()
        for row in original:
            pointer = row["pointer"]
            require(pointer not in seen, "duplicate recovery pointer")
            seen.add(pointer)
            value = payload
            for part in pointer.strip("/").split("/"):
                value = value[int(part)] if isinstance(value, list) else value[part]
            require(
                row["recovery"] == "VERBATIM_RECOVERED"
                and row["sourceSha"] == digest(raw)
                and row["object"] == value,
                "recovered component content or provenance changed",
            )
        receipts[component] = dict(path=name, records=count, file_sha256=digest(raw))
    return receipts


def stage(output, recovery_path, *, report_path=None):
    require(not output.exists(), "output must be a new isolated directory")
    recovered = verify_recovery(recovery_path.read_bytes())
    # New release identity, not an overwrite or relabelling of the historical
    # DRAFT. Every professional record and its lifecycle remains byte-equivalent.
    original = extended_draft()
    candidate = original.model_copy(
        update={"package_id": PACKAGE_ID, "artifact_version": ARTIFACT_VERSION}
    )
    runtime, _ = compile_knowledge_library_v1_1(candidate)
    # Validate every typed consumer before publishing any output. The Dictionary's
    # proposed review state and parametric contract defaults are not rewritten.
    artifacts = load_runtime_artifacts(ROOT, ArtifactVersions(questions="2.0.0", rules="2.0.0"))
    report = active = None
    if report_path is not None:
        report = ProductionValidationReportV1_1.model_validate_json(report_path.read_bytes())
        active = promote_knowledge_runtime_v1_1(runtime, report)
    output.mkdir(parents=True)
    store = KnowledgeArtifactStoreV1_1(output / "knowledge")
    stored = store.publish(candidate)
    manifest = dict(
        purpose="PREPROD_TEXT_ONLY_INTEGRATION; operational evidence, not a new runtime contract",
        semantic=dict(
            package_id=stored.package_id,
            artifact_version=str(stored.artifact_version),
            contract_version="1.1.0",
            source_sha256=stored.source_sha256,
            runtime_sha256=stored.runtime_sha256,
            manifest_sha256=stored.manifest_sha256,
            records=392,
            approved_additions=10,
            source_candidate=dict(
                package_id=original.package_id,
                artifact_version=str(original.artifact_version),
                runtime_sha256=compile_knowledge_library_v1_1(original)[0].sha256,
            ),
            production_validation_report_sha256=report.sha256 if report else None,
        ),
        recovered_components=recovered,
        parametric=dict(
            catalog_id=artifacts.parametric_knowledge.catalog_id,
            artifact_version=str(artifacts.parametric_knowledge.artifact_version),
            typed_runtime_sha256=artifacts.parametric_knowledge.sha256,
            records=584,
            semantics="Exact-context, non-authoritative references; no interpolation",
        ),
        dictionary=dict(
            artifact_version=str(artifacts.dictionary.artifact_version),
            records=21,
            review_status="proposed_pending_domain_review (preserved, not promoted)",
        ),
        consumer_artifacts=[dict(name=k, file_sha256=v) for k, v in artifacts.artifact_hashes],
        versions=vars(artifacts.versions),
        primary_recovered_records=987,
        approved_additional_records=10,
        typed_register_rows=1240,
        gaps=BOUNDED_GAPS,
        status="ACTIVE_EVIDENCE_VERIFIED" if active else "STAGED_NOT_QUALIFIED_NOT_ACTIVE",
    )
    if active:
        (output / "active.json").write_bytes(canonical(active.model_dump(mode="json")) + b"\n")
        (output / "validation-report.json").write_bytes(
            canonical(report.model_dump(mode="json")) + b"\n"
        )
        store.load_active_runtime(
            stored.package_id,
            str(stored.artifact_version),
            active_release=active,
            validation_report=report,
        )
    (output / "integration-manifest.json").write_bytes(canonical(manifest) + b"\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recovered-records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validation-report", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            stage(args.output, args.recovered_records, report_path=args.validation_report), indent=2
        )
    )
