import json

import pytest
from test_knowledge_library import bundle

from jewelai_domain.knowledge_activation import (
    REQUIRED_PRODUCTION_VALIDATION_CHECKS,
    ProductionValidationCheck,
    ProductionValidationReport,
    promote_knowledge_runtime,
)
from jewelai_domain.knowledge_library import (
    compile_knowledge_library,
    validate_knowledge_library,
)
from jewelai_domain.knowledge_storage import (
    KnowledgeArtifactStorageError,
    KnowledgeArtifactStore,
)


def _compiled(payload=None):
    registry = validate_knowledge_library(payload or bundle())
    runtime, _ = compile_knowledge_library(registry)
    return runtime


def _report(runtime, *, outcome="PASS", omitted=None, evidence_suffix=""):
    omitted = omitted or set()
    return ProductionValidationReport(
        package_id=runtime.package_id,
        artifact_version=runtime.artifact_version,
        runtime_sha256=runtime.sha256,
        checks=tuple(
            ProductionValidationCheck(
                name=name,
                outcome=outcome,
                evidence_ref=f"ci://{name}{evidence_suffix}",
            )
            for name in REQUIRED_PRODUCTION_VALIDATION_CHECKS
            if name not in omitted
        ),
    )


def _active_evidence(runtime):
    validation = _report(runtime)
    return promote_knowledge_runtime(runtime, validation), validation


def test_publish_round_trip_is_durable_and_idempotent(tmp_path):
    store = KnowledgeArtifactStore(tmp_path)
    first = store.publish(bundle())
    second = store.publish(bundle())

    assert first == second
    assert first.package_id == "jewelai.test.solitaire"
    assert first.artifact_version == "0.3.0"
    assert len(first.source_sha256) == 64
    assert len(first.runtime_sha256) == 64
    assert len(first.manifest_sha256) == 64

    release = tmp_path / "jewelai.test.solitaire" / "0.3.0"
    assert sorted(path.name for path in release.iterdir()) == [
        "checksums.json",
        "manifest.json",
        "runtime.json",
        "source.json",
    ]
    assert store.load(first.package_id, first.artifact_version) == first


def test_publish_rejects_same_identity_with_different_content(tmp_path):
    store = KnowledgeArtifactStore(tmp_path)
    store.publish(bundle())
    changed = bundle()
    changed["claims"][0]["statement"] = "Changed reviewed claim."

    with pytest.raises(KnowledgeArtifactStorageError, match="different content"):
        store.publish(changed)


def test_load_fails_closed_after_tampering(tmp_path):
    store = KnowledgeArtifactStore(tmp_path)
    stored = store.publish(bundle())
    source_path = tmp_path / stored.package_id / stored.artifact_version / "source.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["claims"][0]["statement"] = "Tampered"
    source_path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(KnowledgeArtifactStorageError, match="checksum mismatch"):
        store.load(stored.package_id, stored.artifact_version)


def test_load_active_runtime_returns_verified_durable_runtime_deterministically(tmp_path):
    store = KnowledgeArtifactStore(tmp_path)
    stored = store.publish(bundle())
    runtime = _compiled()
    active, validation = _active_evidence(runtime)

    first = store.load_active_runtime(
        stored.package_id,
        stored.artifact_version,
        active_release=active,
        validation_report=validation,
    )
    second = store.load_active_runtime(
        stored.package_id,
        stored.artifact_version,
        active_release=active,
        validation_report=validation,
    )

    assert first == second
    assert first == active
    assert first.compiled_runtime == runtime
    assert first.compiled_runtime is not active.compiled_runtime
    assert first.runtime_sha256 == stored.runtime_sha256
    assert first.validation_report_sha256 == validation.sha256


@pytest.mark.parametrize("active_release_factory", [lambda runtime: None, lambda runtime: runtime])
def test_load_active_runtime_requires_active_envelope(tmp_path, active_release_factory):
    store = KnowledgeArtifactStore(tmp_path)
    stored = store.publish(bundle())
    runtime = _compiled()
    validation = _report(runtime)

    with pytest.raises(KnowledgeArtifactStorageError, match="envelope is missing or invalid"):
        store.load_active_runtime(
            stored.package_id,
            stored.artifact_version,
            active_release=active_release_factory(runtime),
            validation_report=validation,
        )


@pytest.mark.parametrize(
    "package_id,artifact_version",
    [
        ("jewelai.test.other", "0.3.0"),
        ("jewelai.test.solitaire", "0.4.0"),
    ],
)
def test_load_active_runtime_rejects_selected_identity_mismatch(
    tmp_path, package_id, artifact_version
):
    store = KnowledgeArtifactStore(tmp_path)
    store.publish(bundle())
    active, validation = _active_evidence(_compiled())

    with pytest.raises(KnowledgeArtifactStorageError, match="explicitly selected release"):
        store.load_active_runtime(
            package_id,
            artifact_version,
            active_release=active,
            validation_report=validation,
        )


def test_load_active_runtime_rejects_durable_runtime_mismatch(tmp_path):
    store = KnowledgeArtifactStore(tmp_path)
    stored = store.publish(bundle())
    changed = bundle()
    changed["claims"][0]["statement"] = "A different reviewed claim."
    other_runtime = _compiled(changed)
    active, validation = _active_evidence(other_runtime)

    with pytest.raises(KnowledgeArtifactStorageError, match="runtime SHA-256"):
        store.load_active_runtime(
            stored.package_id,
            stored.artifact_version,
            active_release=active,
            validation_report=validation,
        )


def test_load_active_runtime_rejects_validation_report_hash_mismatch(tmp_path):
    store = KnowledgeArtifactStore(tmp_path)
    stored = store.publish(bundle())
    runtime = _compiled()
    active, _ = _active_evidence(runtime)
    different_report = _report(runtime, evidence_suffix="-different")

    with pytest.raises(KnowledgeArtifactStorageError, match="report SHA-256"):
        store.load_active_runtime(
            stored.package_id,
            stored.artifact_version,
            active_release=active,
            validation_report=different_report,
        )


@pytest.mark.parametrize("outcome", ["EXPECTED_GAP", "FAIL"])
def test_load_active_runtime_rejects_non_pass_validation(tmp_path, outcome):
    store = KnowledgeArtifactStore(tmp_path)
    stored = store.publish(bundle())
    runtime = _compiled()
    active, _ = _active_evidence(runtime)

    with pytest.raises(KnowledgeArtifactStorageError, match="does not approve"):
        store.load_active_runtime(
            stored.package_id,
            stored.artifact_version,
            active_release=active,
            validation_report=_report(runtime, outcome=outcome),
        )


def test_load_active_runtime_rejects_incomplete_validation(tmp_path):
    store = KnowledgeArtifactStore(tmp_path)
    stored = store.publish(bundle())
    runtime = _compiled()
    active, _ = _active_evidence(runtime)

    with pytest.raises(KnowledgeArtifactStorageError, match="does not approve"):
        store.load_active_runtime(
            stored.package_id,
            stored.artifact_version,
            active_release=active,
            validation_report=_report(runtime, omitted={"behavioral_regression"}),
        )


def test_load_active_runtime_rejects_missing_or_altered_artifacts(tmp_path):
    store = KnowledgeArtifactStore(tmp_path)
    stored = store.publish(bundle())
    active, validation = _active_evidence(_compiled())
    release = tmp_path / stored.package_id / stored.artifact_version
    (release / "manifest.json").unlink()

    with pytest.raises(KnowledgeArtifactStorageError, match="missing files"):
        store.load_active_runtime(
            stored.package_id,
            stored.artifact_version,
            active_release=active,
            validation_report=validation,
        )

    altered_store = KnowledgeArtifactStore(tmp_path / "altered")
    altered = altered_store.publish(bundle())
    runtime_path = (
        tmp_path / "altered" / altered.package_id / altered.artifact_version / "runtime.json"
    )
    runtime_path.write_text(runtime_path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(KnowledgeArtifactStorageError, match="checksum mismatch"):
        altered_store.load_active_runtime(
            altered.package_id,
            altered.artifact_version,
            active_release=active,
            validation_report=validation,
        )


def test_load_active_runtime_never_falls_back_to_another_version(tmp_path):
    store = KnowledgeArtifactStore(tmp_path)
    store.publish(bundle())
    newer = bundle()
    newer["artifact_version"] = "0.4.0"
    store.publish(newer)
    absent = bundle()
    absent["artifact_version"] = "9.9.9"
    active, validation = _active_evidence(_compiled(absent))

    with pytest.raises(KnowledgeArtifactStorageError, match="missing files"):
        store.load_active_runtime(
            "jewelai.test.solitaire",
            "9.9.9",
            active_release=active,
            validation_report=validation,
        )


@pytest.mark.parametrize(
    "package_id,version",
    [
        ("../escape", "1.0.0"),
        ("safe.package", "../1.0.0"),
        ("safe.package", ".."),
        ("safe.package", "."),
        ("safe.package", "1.0"),
        ("safe package", "1.0.0"),
        ("safe/package", "1.0.0"),
    ],
)
def test_storage_rejects_unsafe_paths(tmp_path, package_id, version):
    store = KnowledgeArtifactStore(tmp_path)
    with pytest.raises(KnowledgeArtifactStorageError, match="unsafe"):
        store.load(package_id, version)
