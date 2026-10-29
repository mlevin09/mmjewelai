"""Exact Knowledge version dispatch and immutable verified release identity.

No session, database, provider or activation authority lives here.
"""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import StringConstraints, model_validator

from .knowledge_activation import ActiveKnowledgeRuntime, ProductionValidationReport
from .knowledge_activation_v1_1 import ActiveKnowledgeRuntimeV1_1, ProductionValidationReportV1_1
from .knowledge_library import CompiledKnowledgeLibrary
from .knowledge_library_v1_1 import CompiledKnowledgeLibraryV1_1
from .knowledge_storage import KnowledgeArtifactStore
from .knowledge_storage_v1_1 import KnowledgeArtifactStoreV1_1
from .models import ImmutableModel, Version

KnowledgeContractVersion = Literal["1.0.0", "1.1.0"]
AnyCompiledKnowledge = CompiledKnowledgeLibrary | CompiledKnowledgeLibraryV1_1
AnyActiveKnowledge = ActiveKnowledgeRuntime | ActiveKnowledgeRuntimeV1_1
AnyKnowledgeStore = KnowledgeArtifactStore | KnowledgeArtifactStoreV1_1
AnyValidationReport = ProductionValidationReport | ProductionValidationReportV1_1


def knowledge_contract_version(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if not isinstance(value, dict):
        raise ValueError("Knowledge release must be a typed object or mapping")
    payload = value
    version = payload.get("contract_version")
    if version not in ("1.0.0", "1.1.0") or payload.get("schema_version") != version:
        raise ValueError("Knowledge contract/schema identity is missing or unsupported")
    return version


def validate_compiled_knowledge(value: object) -> AnyCompiledKnowledge:
    version = knowledge_contract_version(value)
    model = CompiledKnowledgeLibrary if version == "1.0.0" else CompiledKnowledgeLibraryV1_1
    return model.model_validate(value)


def validate_active_knowledge(value: object) -> AnyActiveKnowledge:
    version = knowledge_contract_version(value)
    model = ActiveKnowledgeRuntime if version == "1.0.0" else ActiveKnowledgeRuntimeV1_1
    return model.model_validate(value)


def knowledge_store(version, root):
    if version == "1.0.0":
        return KnowledgeArtifactStore(root)
    if version == "1.1.0":
        return KnowledgeArtifactStoreV1_1(root)
    raise ValueError("Unsupported Knowledge contract version")


def knowledge_store_version(store):
    if isinstance(store, KnowledgeArtifactStoreV1_1):
        return "1.1.0"
    if isinstance(store, KnowledgeArtifactStore):
        return "1.0.0"
    raise ValueError("Unsupported Knowledge artifact store")


def digest(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


class KnowledgeReleaseBinding(ImmutableModel):
    binding_version: Literal["1.0.0"]
    knowledge_contract_version: KnowledgeContractVersion
    knowledge_schema_version: KnowledgeContractVersion
    package_id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]+$")]
    artifact_version: Version
    runtime_sha256: str
    validation_report_sha256: str
    active_envelope_sha256: str
    source_sha256: str
    manifest_sha256: str
    content_hash: str

    @model_validator(mode="after")
    def validate_identity(self):
        if self.knowledge_contract_version != self.knowledge_schema_version:
            raise ValueError("Knowledge binding version mismatch")
        if any(
            len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
            for value in (
                self.runtime_sha256,
                self.validation_report_sha256,
                self.active_envelope_sha256,
                self.source_sha256,
                self.manifest_sha256,
                self.content_hash,
            )
        ):
            raise ValueError("Invalid Knowledge binding hash")
        if self.content_hash != digest(self.model_dump(mode="json", exclude={"content_hash"})):
            raise ValueError("Knowledge binding content hash mismatch")
        return self

    @property
    def release_identity(self):
        return (
            self.package_id,
            self.artifact_version,
            self.runtime_sha256,
            self.validation_report_sha256,
        )


def bind_verified_release(
    store, package_id, artifact_version, *, active_release, validation_report
):
    version = knowledge_store_version(store)
    if (
        knowledge_contract_version(active_release) != version
        or knowledge_contract_version(validation_report) != version
    ):
        raise ValueError("Knowledge release evidence version mismatch")
    active = store.load_active_runtime(
        package_id,
        artifact_version,
        active_release=active_release,
        validation_report=validation_report,
    )
    stored = store.load(package_id, artifact_version)
    if stored.runtime_sha256 != active.runtime_sha256:
        raise ValueError("Knowledge source/manifest runtime identity changed during verification")
    payload = dict(
        binding_version="1.0.0",
        knowledge_contract_version=version,
        knowledge_schema_version=version,
        package_id=active.package_id,
        artifact_version=str(active.artifact_version),
        runtime_sha256=active.runtime_sha256,
        validation_report_sha256=active.validation_report_sha256,
        active_envelope_sha256=digest(active),
        source_sha256=stored.source_sha256,
        manifest_sha256=stored.manifest_sha256,
    )
    return KnowledgeReleaseBinding(**payload, content_hash=digest(payload))
