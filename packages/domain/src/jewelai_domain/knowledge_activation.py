"""Fail-closed production validation and ACTIVE promotion for Knowledge Library runtimes."""

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .knowledge_library import (
    KNOWLEDGE_LIBRARY_CONTRACT_VERSION,
    KNOWLEDGE_LIBRARY_SCHEMA_VERSION,
    CompiledKnowledgeLibrary,
)
from .models import ImmutableModel, Version

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class KnowledgeActivationError(ValueError):
    """Raised when a compiled Knowledge Library runtime is not eligible for ACTIVE promotion."""


class ProductionValidationStatus(StrEnum):
    INCOMPLETE = "INCOMPLETE"
    BLOCKED = "BLOCKED"
    ELIGIBLE = "ELIGIBLE"


class ValidationOutcome(StrEnum):
    PASS = "PASS"
    EXPECTED_GAP = "EXPECTED_GAP"
    FAIL = "FAIL"


class ProductionValidationCheckId(StrEnum):
    COMPILER_CONTRACT = "compiler_contract"
    PROVENANCE_INTEGRITY = "provenance_integrity"
    LANGUAGE_MATCHER = "language_matcher"
    RUNTIME_POLICY = "runtime_policy"
    PROMPT_ENRICHMENT = "prompt_enrichment_integration"
    BEHAVIORAL_REGRESSION = "behavioral_regression"


REQUIRED_PRODUCTION_VALIDATION_CHECKS = tuple(check.value for check in ProductionValidationCheckId)
_REQUIRED_PRODUCTION_CHECKS = frozenset(ProductionValidationCheckId)


class ProductionValidationCheck(ImmutableModel):
    name: ProductionValidationCheckId
    outcome: ValidationOutcome
    evidence_ref: Annotated[str, StringConstraints(min_length=1)]
    details: str | None = None


class ProductionValidationReport(ImmutableModel):
    contract_version: Literal["1.0.0"] = KNOWLEDGE_LIBRARY_CONTRACT_VERSION
    schema_version: Literal["1.0.0"] = KNOWLEDGE_LIBRARY_SCHEMA_VERSION
    package_id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]+$")]
    artifact_version: Version
    runtime_sha256: Sha256
    checks: Annotated[tuple[ProductionValidationCheck, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_checks(self):
        check_ids = [check.name for check in self.checks]
        if len(set(check_ids)) != len(check_ids):
            raise ValueError("production validation check IDs must be unique")
        return self

    @property
    def status(self) -> ProductionValidationStatus:
        present = {check.name for check in self.checks}
        if not _REQUIRED_PRODUCTION_CHECKS.issubset(present):
            return ProductionValidationStatus.INCOMPLETE
        if any(check.outcome != ValidationOutcome.PASS for check in self.checks):
            return ProductionValidationStatus.BLOCKED
        return ProductionValidationStatus.ELIGIBLE

    def canonical_json(self) -> str:
        payload = self.model_dump(mode="json")
        payload["checks"] = sorted(payload["checks"], key=lambda check: check["name"])
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class ActiveKnowledgeRuntime(ImmutableModel):
    """Immutable activation envelope; the compiler-owned runtime remains COMPILED."""

    contract_version: Literal["1.0.0"] = KNOWLEDGE_LIBRARY_CONTRACT_VERSION
    schema_version: Literal["1.0.0"] = KNOWLEDGE_LIBRARY_SCHEMA_VERSION
    package_id: str
    artifact_version: Version
    runtime_sha256: Sha256
    validation_report_sha256: Sha256
    lifecycle_status: Literal["ACTIVE"] = "ACTIVE"
    active_for_production: Literal[True] = True
    compiled_runtime: CompiledKnowledgeLibrary

    @model_validator(mode="after")
    def validate_runtime_identity(self):
        runtime = self.compiled_runtime
        if (
            self.package_id != runtime.package_id
            or self.artifact_version != runtime.artifact_version
            or self.runtime_sha256 != runtime.sha256
        ):
            raise ValueError("ACTIVE release identity must match its compiled runtime")
        if runtime.active_for_production is not False:
            raise ValueError("compiler-owned runtime must remain non-ACTIVE")
        return self


def validate_for_production(
    runtime: CompiledKnowledgeLibrary,
    report: ProductionValidationReport,
) -> None:
    """Validate a pinned runtime and its external validation evidence fail-closed."""

    identity_mismatches = []
    if report.contract_version != runtime.contract_version:
        identity_mismatches.append("contract_version")
    if report.schema_version != runtime.schema_version:
        identity_mismatches.append("schema_version")
    if report.package_id != runtime.package_id:
        identity_mismatches.append("package_id")
    if report.artifact_version != runtime.artifact_version:
        identity_mismatches.append("artifact_version")
    if report.runtime_sha256 != runtime.sha256:
        identity_mismatches.append("runtime_sha256")
    if identity_mismatches:
        raise KnowledgeActivationError(
            "production validation evidence does not match runtime identity: "
            + ", ".join(identity_mismatches)
        )

    checks = {check.name: check for check in report.checks}
    missing = sorted(check.value for check in _REQUIRED_PRODUCTION_CHECKS - checks.keys())
    if missing:
        raise KnowledgeActivationError(f"missing required production validation checks: {missing}")

    non_pass = sorted(
        (check.name.value, check.outcome.value)
        for check in report.checks
        if check.outcome != ValidationOutcome.PASS
    )
    if non_pass:
        raise KnowledgeActivationError(
            "all production validation checks must PASS; "
            "EXPECTED_GAP never counts as PASS: "
            f"{non_pass}"
        )


def promote_knowledge_runtime(
    runtime: CompiledKnowledgeLibrary,
    report: ProductionValidationReport,
) -> ActiveKnowledgeRuntime:
    """Promote one exact COMPILED runtime through the production gate without mutating it."""

    if report.status != ProductionValidationStatus.ELIGIBLE:
        raise KnowledgeActivationError(
            f"production validation report is not eligible: {report.status.value}"
        )
    validate_for_production(runtime, report)
    return ActiveKnowledgeRuntime(
        package_id=runtime.package_id,
        artifact_version=runtime.artifact_version,
        runtime_sha256=runtime.sha256,
        validation_report_sha256=report.sha256,
        compiled_runtime=runtime,
    )
