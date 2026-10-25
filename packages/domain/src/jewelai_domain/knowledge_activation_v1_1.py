"""Fail-closed production validation and ACTIVE promotion for Knowledge Library v1.1."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .knowledge_activation import (
    KnowledgeActivationError,
    ProductionValidationCheck,
    ProductionValidationStatus,
    REQUIRED_PRODUCTION_VALIDATION_CHECKS,
    ValidationOutcome,
)
from .knowledge_library_v1_1 import (
    KNOWLEDGE_LIBRARY_CONTRACT_VERSION_V1_1,
    KNOWLEDGE_LIBRARY_SCHEMA_VERSION_V1_1,
    CompiledKnowledgeLibraryV1_1,
)
from .models import ImmutableModel, Version

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ProductionValidationReportV1_1(ImmutableModel):
    contract_version: Literal["1.1.0"] = KNOWLEDGE_LIBRARY_CONTRACT_VERSION_V1_1
    schema_version: Literal["1.1.0"] = KNOWLEDGE_LIBRARY_SCHEMA_VERSION_V1_1
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
        required = set(REQUIRED_PRODUCTION_VALIDATION_CHECKS)
        present = {check.name.value for check in self.checks}
        if not required.issubset(present):
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


class ActiveKnowledgeRuntimeV1_1(ImmutableModel):
    contract_version: Literal["1.1.0"] = KNOWLEDGE_LIBRARY_CONTRACT_VERSION_V1_1
    schema_version: Literal["1.1.0"] = KNOWLEDGE_LIBRARY_SCHEMA_VERSION_V1_1
    package_id: str
    artifact_version: Version
    runtime_sha256: Sha256
    validation_report_sha256: Sha256
    lifecycle_status: Literal["ACTIVE"] = "ACTIVE"
    active_for_production: Literal[True] = True
    compiled_runtime: CompiledKnowledgeLibraryV1_1

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


def validate_for_production_v1_1(
    runtime: CompiledKnowledgeLibraryV1_1,
    report: ProductionValidationReportV1_1,
) -> None:
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

    checks = {check.name.value: check for check in report.checks}
    missing = sorted(set(REQUIRED_PRODUCTION_VALIDATION_CHECKS) - checks.keys())
    if missing:
        raise KnowledgeActivationError(
            f"missing required production validation checks: {missing}"
        )
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


def promote_knowledge_runtime_v1_1(
    runtime: CompiledKnowledgeLibraryV1_1,
    report: ProductionValidationReportV1_1,
) -> ActiveKnowledgeRuntimeV1_1:
    if report.status != ProductionValidationStatus.ELIGIBLE:
        raise KnowledgeActivationError(
            f"production validation report is not eligible: {report.status.value}"
        )
    validate_for_production_v1_1(runtime, report)
    return ActiveKnowledgeRuntimeV1_1(
        package_id=runtime.package_id,
        artifact_version=runtime.artifact_version,
        runtime_sha256=runtime.sha256,
        validation_report_sha256=report.sha256,
        compiled_runtime=runtime,
    )
