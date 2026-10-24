import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from jewelai_domain import (
    REQUIRED_PRODUCTION_VALIDATION_CHECKS,
    KnowledgeReleaseCandidateKind,
    KnowledgeReleaseCandidateSelection,
    KnowledgeReleaseQualification,
    KnowledgeReleaseQualificationBlockerCode,
    KnowledgeReleaseQualificationStatus,
    ProductionValidationCheck,
    ProductionValidationReport,
    compile_knowledge_library,
    promote_knowledge_runtime,
    qualify_knowledge_release,
)
from jewelai_domain.knowledge_preflight import main
from jewelai_domain.knowledge_storage import KnowledgeArtifactStore

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "data" / "knowledge" / "v1" / "three-stone-1.0.0.json"
SOURCE_COMMIT = "3524d4181f9db60286cfd6b543de402e62cf813d"


def _bundle():
    return json.loads(PACKAGE.read_text(encoding="utf-8"))


def _report(runtime, *, outcome="PASS", omitted=()):
    return ProductionValidationReport(
        package_id=runtime.package_id,
        artifact_version=runtime.artifact_version,
        runtime_sha256=runtime.sha256,
        checks=tuple(
            ProductionValidationCheck(
                name=name,
                outcome=outcome,
                evidence_ref=f"synthetic://{name}",
            )
            for name in REQUIRED_PRODUCTION_VALIDATION_CHECKS
            if name not in omitted
        ),
    )


def _candidate(store):
    stored = store.publish(_bundle())
    runtime, _ = compile_knowledge_library(_bundle())
    report = _report(runtime)
    active = promote_knowledge_runtime(runtime, report)
    selection = KnowledgeReleaseCandidateSelection(
        package_id=stored.package_id,
        artifact_version=stored.artifact_version,
        kind=KnowledgeReleaseCandidateKind.SYNTHETIC,
    )
    return stored, runtime, report, active, selection


def test_qualified_synthetic_release_is_deterministic_and_runtime_verified(tmp_path):
    store = KnowledgeArtifactStore(tmp_path)
    stored, runtime, report, active, selection = _candidate(store)

    first = qualify_knowledge_release(
        store,
        selection,
        active_release=active,
        validation_report=report,
        source_commit=SOURCE_COMMIT,
    )
    second = qualify_knowledge_release(
        store,
        selection,
        active_release=active,
        validation_report=report,
        source_commit=SOURCE_COMMIT,
    )

    assert first == second
    assert first.status == KnowledgeReleaseQualificationStatus.QUALIFIED
    assert first.candidate_kind == KnowledgeReleaseCandidateKind.SYNTHETIC
    assert first.package_id == stored.package_id
    assert first.artifact_version == stored.artifact_version
    assert first.runtime_sha256 == runtime.sha256
    assert first.validation_report_sha256 == report.sha256
    assert first.validation_gate_status == "ELIGIBLE"
    assert first.runtime_loader_compatible is True
    assert first.blockers == ()
    assert len(first.qualification_sha256) == 64


def test_no_candidate_is_not_evaluated_and_never_succeeds(tmp_path):
    result = qualify_knowledge_release(
        KnowledgeArtifactStore(tmp_path),
        None,
        source_commit=SOURCE_COMMIT,
    )

    assert result.status == KnowledgeReleaseQualificationStatus.NOT_EVALUATED
    assert result.runtime_loader_compatible is False
    assert result.blockers[0].code == (
        KnowledgeReleaseQualificationBlockerCode.CANDIDATE_NOT_SUPPLIED
    )


@pytest.mark.parametrize(
    ("active", "report", "expected"),
    (
        (None, "valid", KnowledgeReleaseQualificationBlockerCode.ACTIVE_ENVELOPE_MISSING),
        (
            {"invalid": True},
            "valid",
            KnowledgeReleaseQualificationBlockerCode.ACTIVE_ENVELOPE_INVALID,
        ),
        ("valid", None, KnowledgeReleaseQualificationBlockerCode.VALIDATION_REPORT_MISSING),
        (
            "valid",
            {"invalid": True},
            KnowledgeReleaseQualificationBlockerCode.VALIDATION_REPORT_INVALID,
        ),
    ),
)
def test_missing_or_malformed_active_evidence_blocks(tmp_path, active, report, expected):
    store = KnowledgeArtifactStore(tmp_path)
    _, _, valid_report, valid_active, selection = _candidate(store)

    result = qualify_knowledge_release(
        store,
        selection,
        active_release=valid_active if active == "valid" else active,
        validation_report=valid_report if report == "valid" else report,
    )

    assert result.status == KnowledgeReleaseQualificationStatus.BLOCKED
    assert result.blockers[0].code == expected
    assert result.runtime_loader_compatible is False


@pytest.mark.parametrize("outcome", ("EXPECTED_GAP", "FAIL"))
def test_non_pass_validation_gate_blocks_without_runtime_loading(tmp_path, outcome):
    store = KnowledgeArtifactStore(tmp_path)
    _, runtime, _, active, selection = _candidate(store)
    report = _report(runtime, outcome=outcome)

    result = qualify_knowledge_release(
        store,
        selection,
        active_release=active,
        validation_report=report,
    )

    assert result.status == KnowledgeReleaseQualificationStatus.BLOCKED
    assert result.validation_gate_status == "BLOCKED"
    assert result.blockers[0].code == (
        KnowledgeReleaseQualificationBlockerCode.VALIDATION_GATE_BLOCKED
    )


def test_incomplete_behavioral_evidence_blocks(tmp_path):
    store = KnowledgeArtifactStore(tmp_path)
    _, runtime, _, active, selection = _candidate(store)
    report = _report(runtime, omitted={"behavioral_regression"})

    result = qualify_knowledge_release(
        store,
        selection,
        active_release=active,
        validation_report=report,
    )

    assert result.status == KnowledgeReleaseQualificationStatus.BLOCKED
    assert result.validation_gate_status == "INCOMPLETE"
    assert result.blockers[0].code == (
        KnowledgeReleaseQualificationBlockerCode.VALIDATION_GATE_BLOCKED
    )


def test_runtime_tampering_blocks_after_eligible_gate(tmp_path):
    store = KnowledgeArtifactStore(tmp_path)
    stored, _, report, active, selection = _candidate(store)
    runtime_path = tmp_path / stored.package_id / stored.artifact_version / "runtime.json"
    runtime_path.write_text(runtime_path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    result = qualify_knowledge_release(
        store,
        selection,
        active_release=active,
        validation_report=report,
    )

    assert result.status == KnowledgeReleaseQualificationStatus.BLOCKED
    assert result.blockers[0].code == (
        KnowledgeReleaseQualificationBlockerCode.RUNTIME_VERIFICATION_FAILED
    )
    assert "checksum mismatch" in result.blockers[0].detail


def test_report_substitution_and_unavailable_release_block(tmp_path):
    store = KnowledgeArtifactStore(tmp_path)
    stored, runtime, _, active, selection = _candidate(store)
    substituted = ProductionValidationReport(
        package_id=runtime.package_id,
        artifact_version=runtime.artifact_version,
        runtime_sha256=runtime.sha256,
        checks=tuple(
            ProductionValidationCheck(
                name=name,
                outcome="PASS",
                evidence_ref=f"synthetic://replacement/{name}",
            )
            for name in REQUIRED_PRODUCTION_VALIDATION_CHECKS
        ),
    )
    mismatch = qualify_knowledge_release(
        store,
        selection,
        active_release=active,
        validation_report=substituted,
    )
    absent_bundle = _bundle()
    absent_bundle["artifact_version"] = "9.9.9"
    absent_runtime, _ = compile_knowledge_library(absent_bundle)
    absent_report = _report(absent_runtime)
    absent_active = promote_knowledge_runtime(absent_runtime, absent_report)
    missing = qualify_knowledge_release(
        store,
        {
            "package_id": stored.package_id,
            "artifact_version": "9.9.9",
            "kind": "SYNTHETIC",
        },
        active_release=absent_active,
        validation_report=absent_report,
    )

    assert mismatch.status == KnowledgeReleaseQualificationStatus.BLOCKED
    assert "report SHA-256" in mismatch.blockers[0].detail
    assert missing.status == KnowledgeReleaseQualificationStatus.BLOCKED
    assert missing.blockers[0].code == (
        KnowledgeReleaseQualificationBlockerCode.RUNTIME_VERIFICATION_FAILED
    )


def test_invalid_candidate_and_qualification_hash_fail_closed(tmp_path):
    invalid = qualify_knowledge_release(
        KnowledgeArtifactStore(tmp_path),
        {"package_id": "../escape", "artifact_version": "latest", "kind": "SYNTHETIC"},
    )

    assert invalid.status == KnowledgeReleaseQualificationStatus.BLOCKED
    assert invalid.blockers[0].code == KnowledgeReleaseQualificationBlockerCode.CANDIDATE_INVALID

    payload = invalid.model_dump(mode="json")
    payload["qualification_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="qualification hash mismatch"):
        KnowledgeReleaseQualification.model_validate(payload)


def test_read_only_preflight_command_emits_canonical_qualified_evidence(
    tmp_path, monkeypatch, capsys
):
    store = KnowledgeArtifactStore(tmp_path / "knowledge")
    stored, _, report, active, _ = _candidate(store)
    active_path = tmp_path / "active.json"
    report_path = tmp_path / "report.json"
    active_path.write_text(active.model_dump_json(), encoding="utf-8")
    report_path.write_text(report.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "knowledge_preflight",
            "--artifact-root",
            str(tmp_path / "knowledge"),
            "--package-id",
            stored.package_id,
            "--artifact-version",
            stored.artifact_version,
            "--active-release",
            str(active_path),
            "--validation-report",
            str(report_path),
            "--candidate-kind",
            "SYNTHETIC",
            "--source-commit",
            SOURCE_COMMIT,
        ],
    )

    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "QUALIFIED"
    assert output["candidate_kind"] == "SYNTHETIC"
    assert output["runtime_loader_compatible"] is True


def test_read_only_preflight_command_reports_not_evaluated_without_candidate(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        sys,
        "argv",
        ["knowledge_preflight", "--artifact-root", str(tmp_path)],
    )

    assert main() == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "NOT_EVALUATED"
