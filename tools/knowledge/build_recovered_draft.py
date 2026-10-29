"""Offline, explicit record projection of the authenticated KNA2-009 core subset.

Not a catalog-authoring, approval, activation, or session-startup command. The
historical source remains intact; every projected record is compared with its
recovered original. Unsupported historical structures remain evidence only.
"""

import argparse
import hashlib
import json
from pathlib import Path

from jewelai_domain.knowledge_library import KnowledgeLibraryBundle, compile_knowledge_library
from jewelai_domain.knowledge_library_v1_1 import (
    KnowledgeLibraryBundleV1_1,
    compile_knowledge_library_v1_1,
)
from jewelai_domain.knowledge_storage_v1_1 import KnowledgeArtifactStoreV1_1
from jewelai_domain.knowledge_targets_v1_1 import POLICY_TARGET_TEMPLATES_V1_1

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/knowledge/v1/jewelry-core-1.0.0.json"
SOURCE_SHA256 = "fdccf31bfa873a7330da8997ab1d95e04a65c422592df0eff78825c022917b10"
RECOVERY_SHA256 = "a47e93d9d3860ab54fdd4ee36bc7ff95bc39ad1821ad5830d8ed2ef98c8eaed4"
HISTORICAL_COMMIT = "6772a7b2436b6cb97a898680e978ca6dc37624a3"
PACKAGE_ID = "jewelai.draft.recovered_core"
ARTIFACT_VERSION = "0.1.0"
RECORD_GROUPS = {
    "sources": "source_id",
    "claims": "claim_id",
    "domain_knowledge": "concept_id",
    "language_mappings": "mapping_id",
    "policies": "policy_id",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise ValueError(detail)


def project_core(source_bytes: bytes) -> KnowledgeLibraryBundleV1_1:
    """Explicit, lossless projection of shared record contracts, never a fallback.

    The hash allowlist is intentionally this one authenticated source, not an
    arbitrary v1.0 -> v1.1 migration API. New policy bindings require new review.
    """
    require(sha256(source_bytes) == SOURCE_SHA256, "unauthenticated core source bytes")
    original = KnowledgeLibraryBundle.model_validate_json(source_bytes)
    legacy, _ = compile_knowledge_library(original)
    require(not legacy.active_for_production, "source must not confer activation")
    for policy in original.policies:
        require(policy.target in POLICY_TARGET_TEMPLATES_V1_1, "unapproved target projection")
    candidate = KnowledgeLibraryBundleV1_1(
        package_id=PACKAGE_ID,
        artifact_version=ARTIFACT_VERSION,
        # Source/Claim/DomainKnowledge/LanguageMapping are the SAME contract
        # classes in v1.1. Policy differs only in validated target grammar.
        sources=original.sources,
        claims=original.claims,
        domain_knowledge=original.domain_knowledge,
        language_mappings=original.language_mappings,
        policies=tuple(item.model_dump(mode="json") for item in original.policies),
    )
    for group in RECORD_GROUPS:
        require(
            [item.model_dump(mode="json") for item in getattr(original, group)]
            == [item.model_dump(mode="json") for item in getattr(candidate, group)],
            f"record projection changed {group}",
        )
    compile_knowledge_library_v1_1(candidate)
    return candidate


def reconcile_recovery(candidate, source_bytes: bytes, recovery_bytes: bytes):
    require(candidate == project_core(source_bytes), "candidate differs from verified projection")
    require(sha256(recovery_bytes) == RECOVERY_SHA256, "unauthenticated recovery register")
    recovery = json.loads(recovery_bytes)
    original = json.loads(source_bytes)
    included, excluded = [], []
    expected = {}
    for group, id_field in RECORD_GROUPS.items():
        for index, record in enumerate(original[group]):
            expected[f"/{group}/{index}"] = (record[id_field], record)
    seen = set()
    for recovered in recovery:
        if recovered["file"] != "data/knowledge/v1/jewelry-core-1.0.0.json":
            excluded.append(
                {
                    "nav": recovered["nav"],
                    "record_id": recovered["id"],
                    "type": recovered["type"],
                    "classification": recovered["recovery"],
                    "source_locator": recovered["url"],
                    "pointer": recovered["pointer"],
                    "reason": (
                        "Source not retrieved; no approval inferred"
                        if recovered["recovery"] == "SOURCE_NOT_ACCESSIBLE"
                        else "Summary is not item-level professional content"
                        if recovered["recovery"] == "ARCHITECTURAL_SUMMARY_ONLY"
                        else ("Outside core projection; retained unchanged in recovery evidence")
                    ),
                }
            )
            continue
        pointer = recovered["pointer"]
        require(
            pointer in expected and pointer not in seen, "unexpected/duplicate recovery pointer"
        )
        record_id, record = expected[pointer]
        require(
            recovered["id"] == record_id
            and recovered["object"] == record
            and recovered["sourceSha"] == SOURCE_SHA256
            and recovered["recovery"] == "VERBATIM_RECOVERED"
            and recovered["lifecycle"] == record["lifecycle_status"],
            "recovered record does not match authenticated original",
        )
        seen.add(pointer)
        group, index = pointer.strip("/").split("/")
        packaged = getattr(candidate, group)[int(index)].model_dump(mode="json")
        included.append(
            {
                "original_record_id": record_id,
                "packaged_record_id": record_id,
                "type": recovered["type"],
                "classification": recovered["recovery"],
                "lifecycle_status": recovered["lifecycle"],
                "source_locator": recovered["url"],
                "source_pointer": pointer,
                "source_sha256": SOURCE_SHA256,
                "original_record": record,
                "packaged_record": packaged,
                "target": record.get("target"),
                "decision": "INCLUDED_UNCHANGED_SHARED_RECORD_CONTRACT",
                "limitation": (
                    "Later core evidence; original P0 chapter authorship linkage unverified"
                ),
            }
        )
    require(seen == set(expected), "missing recovered core records")
    require(len(included) + len(excluded) == len(recovery), "unaccounted recovery rows")
    return included, excluded


def build(output: Path, recovery_path: Path):
    """Stage four ADR 0029 artifacts locally; never create an ACTIVE envelope."""
    require(not output.exists(), "output must be a new isolated DRAFT directory")
    source_bytes = SOURCE.read_bytes()
    recovery_bytes = recovery_path.read_bytes()
    candidate = project_core(source_bytes)
    included, excluded = reconcile_recovery(candidate, source_bytes, recovery_bytes)
    runtime, manifest = compile_knowledge_library_v1_1(candidate)
    output.mkdir(parents=True)
    store = KnowledgeArtifactStoreV1_1(output / "draft-store")
    stored = store.publish(candidate)
    require(store.publish(candidate) == stored, "immutable staging is not idempotent")
    require(store.load(PACKAGE_ID, ARTIFACT_VERSION) == stored, "reload mismatch")
    require(compile_knowledge_library_v1_1(candidate)[0] == runtime, "nondeterministic compiler")
    for name, value in (
        ("inclusion-register.json", included),
        ("exclusion-register.json", excluded),
    ):
        (output / name).write_bytes(canonical(value) + b"\n")
    # Preserve the complete corpus as evidence, including every excluded record.
    (output / "recovered-records.json").write_bytes(recovery_bytes)
    (output / "historical-core.json").write_bytes(source_bytes)
    inventory = {
        "status": "DRAFT_PARTIAL_SHARED_CORE_PROJECTION_NOT_ACTIVE",
        "package_id": PACKAGE_ID,
        "artifact_version": ARTIFACT_VERSION,
        "contract_version": candidate.contract_version,
        "schema_version": runtime.schema_version,
        "runtime_sha256": runtime.sha256,
        "source_sha256": stored.source_sha256,
        "manifest_sha256": stored.manifest_sha256,
        "historical_source_commit": HISTORICAL_COMMIT,
        "historical_source_sha256": SOURCE_SHA256,
        "recovery_register_sha256": RECOVERY_SHA256,
        "record_counts": {group: len(getattr(candidate, group)) for group in RECORD_GROUPS},
        "recovered_rows": len(included) + len(excluded),
        "excluded_rows": len(excluded),
        "additive_v1_1_policy_records": 0,
        "projection": (
            "Shared record classes and exact policy targets are unchanged; only package identity "
            "and validated contract dispatch differ. This is not the full P0 v1.1 catalog."
        ),
        "files": {
            str(path.relative_to(output)): sha256(path.read_bytes())
            for path in sorted(output.rglob("*"))
            if path.is_file()
        },
    }
    require(manifest.runtime_sha256 == inventory["runtime_sha256"], "manifest mismatch")
    (output / "candidate-inventory.json").write_bytes(canonical(inventory) + b"\n")
    return inventory


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recovered-records", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.output, arguments.recovered_records), indent=2))
