from jewelai_domain.knowledge_activation import (
    REQUIRED_PRODUCTION_VALIDATION_CHECKS,
    KnowledgeActivationError,
    ProductionValidationCheck,
    ProductionValidationReport,
    ProductionValidationStatus,
    promote_knowledge_runtime,
)
from jewelai_domain.knowledge_library import CompiledKnowledgeLibrary


def runtime():
    return CompiledKnowledgeLibrary(
        package_id="jewelai.test.activation",
        artifact_version="1.0.0",
        sources=(),
        claims=(),
        domain_knowledge=(),
        language_mappings=(),
        policies=(),
    )


def report(compiled, *, outcome="PASS", names=None):
    names = names or REQUIRED_PRODUCTION_VALIDATION_CHECKS
    return ProductionValidationReport(
        package_id=compiled.package_id,
        artifact_version=compiled.artifact_version,
        runtime_sha256=compiled.sha256,
        checks=tuple(
            ProductionValidationCheck(
                name=name,
                outcome=outcome,
                evidence_ref=f"ci://{name}",
            )
            for name in names
        ),
    )


def test_complete_pass_report_is_eligible_and_promotes_exact_runtime():
    compiled = runtime()
    validation = report(compiled)

    assert validation.status == ProductionValidationStatus.ELIGIBLE
    active = promote_knowledge_runtime(compiled, validation)

    assert active.package_id == compiled.package_id
    assert active.artifact_version == compiled.artifact_version
    assert active.runtime_sha256 == compiled.sha256
    assert active.validation_report_sha256 == validation.sha256
    assert active.active_for_production is True
    assert {item.name for item in validation.checks} == set(
        REQUIRED_PRODUCTION_VALIDATION_CHECKS
    )


def test_expected_gap_blocks_promotion():
    compiled = runtime()
    validation = ProductionValidationReport(
        package_id=compiled.package_id,
        artifact_version=compiled.artifact_version,
        runtime_sha256=compiled.sha256,
        checks=tuple(
            ProductionValidationCheck(
                name=name,
                outcome="EXPECTED_GAP" if name == "behavioral_regression" else "PASS",
                evidence_ref=f"ci://{name}",
            )
            for name in REQUIRED_PRODUCTION_VALIDATION_CHECKS
        ),
    )

    assert validation.status == ProductionValidationStatus.BLOCKED
    try:
        promote_knowledge_runtime(compiled, validation)
    except KnowledgeActivationError as exc:
        assert "not eligible" in str(exc)
    else:
        raise AssertionError("EXPECTED_GAP must block ACTIVE promotion")


def test_fail_blocks_promotion():
    compiled = runtime()
    validation = report(compiled, outcome="FAIL")

    assert validation.status == ProductionValidationStatus.BLOCKED
    try:
        promote_knowledge_runtime(compiled, validation)
    except KnowledgeActivationError as exc:
        assert "not eligible" in str(exc)
    else:
        raise AssertionError("FAIL must block ACTIVE promotion")


def test_missing_required_check_is_incomplete_and_blocks():
    compiled = runtime()
    validation = report(
        compiled,
        names=tuple(
            name
            for name in REQUIRED_PRODUCTION_VALIDATION_CHECKS
            if name != "prompt_enrichment_integration"
        ),
    )

    assert validation.status == ProductionValidationStatus.INCOMPLETE
    try:
        promote_knowledge_runtime(compiled, validation)
    except KnowledgeActivationError as exc:
        assert "not eligible" in str(exc)
    else:
        raise AssertionError("incomplete validation must block ACTIVE promotion")


def test_report_cannot_claim_eligible_or_active():
    compiled = runtime()
    validation = report(compiled)

    payload = validation.model_dump(mode="json")
    assert "active_for_production" not in payload
    assert validation.status == ProductionValidationStatus.ELIGIBLE


def test_runtime_identity_mismatch_blocks_promotion():
    compiled = runtime()
    validation = ProductionValidationReport(
        package_id="jewelai.other",
        artifact_version=compiled.artifact_version,
        runtime_sha256=compiled.sha256,
        checks=report(compiled).checks,
    )

    try:
        promote_knowledge_runtime(compiled, validation)
    except KnowledgeActivationError as exc:
        assert "package_id" in str(exc)
    else:
        raise AssertionError("package mismatch must block promotion")


def test_runtime_hash_mismatch_blocks_promotion():
    compiled = runtime()
    validation = ProductionValidationReport(
        package_id=compiled.package_id,
        artifact_version=compiled.artifact_version,
        runtime_sha256="0" * 64,
        checks=report(compiled).checks,
    )

    try:
        promote_knowledge_runtime(compiled, validation)
    except KnowledgeActivationError as exc:
        assert "runtime_sha256" in str(exc)
    else:
        raise AssertionError("runtime hash mismatch must block promotion")


def test_validation_report_hash_is_deterministic_for_unordered_checks():
    compiled = runtime()
    first = report(compiled)
    second = ProductionValidationReport(
        package_id=compiled.package_id,
        artifact_version=compiled.artifact_version,
        runtime_sha256=compiled.sha256,
        checks=tuple(reversed(first.checks)),
    )

    assert first.canonical_json() == second.canonical_json()
    assert first.sha256 == second.sha256
