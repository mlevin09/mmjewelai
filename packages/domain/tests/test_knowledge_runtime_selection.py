"""Explicit dispatch/binding mechanisms only; synthetic PASS is not catalog qualification."""

from copy import deepcopy

import pytest
from test_p0_21_knowledge_library_v1_1 import bundle_v1_1, report

from jewelai_domain.knowledge_activation_v1_1 import promote_knowledge_runtime_v1_1
from jewelai_domain.knowledge_library_v1_1 import compile_knowledge_library_v1_1
from jewelai_domain.knowledge_runtime import (
    KnowledgeReleaseBinding,
    bind_verified_release,
    digest,
    knowledge_store,
    validate_active_knowledge,
    validate_compiled_knowledge,
)


@pytest.fixture
def release(tmp_path):
    runtime, _ = compile_knowledge_library_v1_1(bundle_v1_1())
    validation = report(runtime)
    active = promote_knowledge_runtime_v1_1(runtime, validation)
    store = knowledge_store("1.1.0", tmp_path)
    store.publish(bundle_v1_1())
    return store, runtime, active, validation


def test_exact_identity_binding_and_unchanged_models(release):
    store, runtime, active, validation = release
    before = runtime.canonical_json()
    first = bind_verified_release(
        store,
        runtime.package_id,
        runtime.artifact_version,
        active_release=active,
        validation_report=validation,
    )
    second = bind_verified_release(
        store,
        runtime.package_id,
        runtime.artifact_version,
        active_release=active,
        validation_report=validation,
    )
    assert first == second
    incomplete = first.model_dump(mode="json")
    del incomplete["binding_version"]
    with pytest.raises(ValueError):
        KnowledgeReleaseBinding.model_validate(incomplete)
    assert first.knowledge_contract_version == "1.1.0" and first.artifact_version == "1.0.0"
    assert first.active_envelope_sha256 == digest(active)
    assert (
        first.source_sha256
        == store.load(runtime.package_id, runtime.artifact_version).source_sha256
    )
    assert (
        first.manifest_sha256
        == store.load(runtime.package_id, runtime.artifact_version).manifest_sha256
    )
    assert validate_compiled_knowledge(runtime).canonical_json() == before
    assert validate_active_knowledge(active).model_dump_json() == active.model_dump_json()


@pytest.mark.parametrize("field", ["contract_version", "schema_version"])
@pytest.mark.parametrize("invalid", [None, "1.2.0", "1.0.0", [], {}])
def test_exact_version_rejection_before_defaulting(release, field, invalid):
    _, runtime, active, _ = release
    for value, validate in (
        (runtime, validate_compiled_knowledge),
        (active, validate_active_knowledge),
    ):
        payload = value.model_dump(mode="json")
        del payload[field]
        with pytest.raises(ValueError):
            validate(payload)
        payload[field] = invalid
        with pytest.raises(ValueError):
            validate(payload)


@pytest.mark.parametrize(
    "field",
    [
        "runtime_sha256",
        "validation_report_sha256",
        "source_sha256",
        "manifest_sha256",
        "active_envelope_sha256",
        "knowledge_schema_version",
        "content_hash",
    ],
)
def test_binding_tamper_and_independent_hashes(release, field):
    store, runtime, active, validation = release
    binding = bind_verified_release(
        store,
        runtime.package_id,
        runtime.artifact_version,
        active_release=active,
        validation_report=validation,
    )
    payload = deepcopy(binding.model_dump(mode="json"))
    payload[field] = "1.0.0" if field == "knowledge_schema_version" else "0" * 64
    with pytest.raises(ValueError):
        KnowledgeReleaseBinding.model_validate(payload)


@pytest.mark.parametrize("name", ["runtime.json", "manifest.json", "source.json", "checksums.json"])
def test_verified_binding_requires_actual_immutable_artifacts(release, name):
    store, runtime, active, validation = release
    path = store.root / runtime.package_id / runtime.artifact_version / name
    path.write_text("{}")
    with pytest.raises(ValueError):
        bind_verified_release(
            store,
            runtime.package_id,
            runtime.artifact_version,
            active_release=active,
            validation_report=validation,
        )


def test_explicit_store_version_never_falls_back(release):
    store, runtime, active, validation = release
    with pytest.raises(ValueError):
        knowledge_store("latest", store.root)
    with pytest.raises(ValueError):
        bind_verified_release(
            knowledge_store("1.0.0", store.root),
            runtime.package_id,
            runtime.artifact_version,
            active_release=active,
            validation_report=validation,
        )


@pytest.mark.parametrize("outcome", ["INCOMPLETE", "EXPECTED_GAP", "FAIL"])
def test_v1_1_non_pass_evidence_never_qualifies(release, outcome):
    from jewelai_domain.knowledge_activation_v1_1 import (
        ProductionValidationReportV1_1,
        promote_knowledge_runtime_v1_1,
    )
    from jewelai_domain.knowledge_qualification import KnowledgeReleaseCandidateSelection
    from jewelai_domain.knowledge_qualification_v1_1 import qualify_knowledge_release_v1_1

    store, runtime, active, validation = release
    payload = validation.model_dump(mode="json")
    if outcome == "INCOMPLETE":
        payload["checks"].pop()
    else:
        payload["checks"][0]["outcome"] = outcome
    invalid = ProductionValidationReportV1_1.model_validate(payload)
    selection = KnowledgeReleaseCandidateSelection(
        package_id=runtime.package_id, artifact_version=runtime.artifact_version, kind="SYNTHETIC"
    )
    result = qualify_knowledge_release_v1_1(
        store, selection, active_release=active, validation_report=invalid
    )
    assert result.status.value == "BLOCKED"
    assert result.blockers[0].code.value == "validation_gate_blocked"
    with pytest.raises(ValueError):
        promote_knowledge_runtime_v1_1(runtime, invalid)
    with pytest.raises(ValueError):
        bind_verified_release(
            store,
            runtime.package_id,
            runtime.artifact_version,
            active_release=active,
            validation_report=invalid,
        )
