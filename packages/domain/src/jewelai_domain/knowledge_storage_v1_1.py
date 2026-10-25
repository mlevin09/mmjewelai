"""Immutable durable storage for Knowledge Library Contract v1.1 artifacts."""

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

from pydantic import ValidationError

from .knowledge_activation import KnowledgeActivationError
from .knowledge_activation_v1_1 import (
    ActiveKnowledgeRuntimeV1_1,
    ProductionValidationReportV1_1,
    validate_for_production_v1_1,
)
from .knowledge_library_v1_1 import (
    CompilationManifestV1_1,
    CompiledKnowledgeLibraryV1_1,
    KnowledgeLibraryBundleV1_1,
    compile_knowledge_library_v1_1,
    validate_knowledge_library_v1_1,
)
from .knowledge_storage import KnowledgeArtifactStorageError, StoredKnowledgeArtifact


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class KnowledgeArtifactStoreV1_1:
    """Content-verified immutable storage for explicit v1.1 package/version releases."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _release_path(self, package_id: str, artifact_version: str) -> Path:
        if re.fullmatch(r"[a-z][a-z0-9_.-]+", package_id) is None:
            raise KnowledgeArtifactStorageError("unsafe knowledge package_id")
        if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", artifact_version) is None:
            raise KnowledgeArtifactStorageError("unsafe knowledge artifact_version")

        root = self.root.resolve()
        release_path = self.root / package_id / artifact_version
        try:
            release_path.resolve().relative_to(root)
        except ValueError as exc:
            raise KnowledgeArtifactStorageError(
                "knowledge artifact path escapes storage root"
            ) from exc
        return release_path

    @staticmethod
    def _payloads(
        bundle: KnowledgeLibraryBundleV1_1,
    ) -> tuple[dict[str, str], CompiledKnowledgeLibraryV1_1]:
        registry = validate_knowledge_library_v1_1(bundle)
        runtime, manifest = compile_knowledge_library_v1_1(registry)
        source_json = _canonical_json(registry.bundle.model_dump(mode="json"))
        runtime_json = runtime.canonical_json()
        manifest_json = _canonical_json(manifest.model_dump(mode="json"))
        checksums_json = _canonical_json(
            {
                "source_sha256": _sha256(source_json),
                "runtime_sha256": _sha256(runtime_json),
                "manifest_sha256": _sha256(manifest_json),
            }
        )
        return (
            {
                "source.json": source_json + "\n",
                "runtime.json": runtime_json + "\n",
                "manifest.json": manifest_json + "\n",
                "checksums.json": checksums_json + "\n",
            },
            runtime,
        )

    @staticmethod
    def _verify_existing(release_path: Path, expected: dict[str, str]) -> None:
        if not release_path.is_dir():
            raise KnowledgeArtifactStorageError(
                f"artifact path is not a directory: {release_path}"
            )
        missing = [name for name in expected if not (release_path / name).is_file()]
        if missing:
            raise KnowledgeArtifactStorageError(
                f"durable artifact is incomplete; missing files: {sorted(missing)}"
            )
        changed = [
            name
            for name, payload in expected.items()
            if (release_path / name).read_text(encoding="utf-8") != payload
        ]
        if changed:
            raise KnowledgeArtifactStorageError(
                "immutable package/version already exists with different content: "
                + ", ".join(sorted(changed))
            )

    def publish(
        self, bundle: KnowledgeLibraryBundleV1_1 | object
    ) -> StoredKnowledgeArtifact:
        validated = validate_knowledge_library_v1_1(bundle).bundle
        if validated.artifact_version is None:
            raise KnowledgeArtifactStorageError(
                "artifact_version is required for durable storage"
            )
        payloads, _ = self._payloads(validated)
        version = str(validated.artifact_version)
        release_path = self._release_path(validated.package_id, version)

        if release_path.exists():
            self._verify_existing(release_path, payloads)
            return self.load(validated.package_id, version)

        release_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{version}-", dir=str(release_path.parent))
        )
        try:
            for name, payload in payloads.items():
                (temporary / name).write_text(payload, encoding="utf-8")
            try:
                temporary.rename(release_path)
            except FileExistsError:
                self._verify_existing(release_path, payloads)
            return self.load(validated.package_id, version)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def _load_verified(
        self,
        package_id: str,
        artifact_version: str,
    ) -> tuple[StoredKnowledgeArtifact, CompiledKnowledgeLibraryV1_1]:
        release_path = self._release_path(package_id, artifact_version)
        required = ("source.json", "runtime.json", "manifest.json", "checksums.json")
        missing = [name for name in required if not (release_path / name).is_file()]
        if missing:
            raise KnowledgeArtifactStorageError(
                f"durable artifact is incomplete; missing files: {sorted(missing)}"
            )

        raw = {
            name: (release_path / name).read_text(encoding="utf-8").rstrip("\n")
            for name in required
        }
        try:
            source = KnowledgeLibraryBundleV1_1.model_validate_json(raw["source.json"])
            stored_runtime = CompiledKnowledgeLibraryV1_1.model_validate_json(
                raw["runtime.json"]
            )
            stored_manifest = CompilationManifestV1_1.model_validate_json(
                raw["manifest.json"]
            )
            checksums = json.loads(raw["checksums.json"])
        except (ValidationError, json.JSONDecodeError) as exc:
            raise KnowledgeArtifactStorageError(
                "stored Knowledge Library v1.1 artifact is invalid"
            ) from exc

        expected_runtime, expected_manifest = compile_knowledge_library_v1_1(source)
        expected_checksums = {
            "source_sha256": _sha256(raw["source.json"]),
            "runtime_sha256": _sha256(raw["runtime.json"]),
            "manifest_sha256": _sha256(raw["manifest.json"]),
        }
        if checksums != expected_checksums:
            raise KnowledgeArtifactStorageError(
                "stored knowledge artifact checksum mismatch"
            )
        if stored_runtime != expected_runtime:
            raise KnowledgeArtifactStorageError(
                "stored runtime does not match deterministic v1.1 compiler"
            )
        if stored_manifest != expected_manifest:
            raise KnowledgeArtifactStorageError(
                "stored manifest does not match deterministic v1.1 compiler"
            )
        if (
            source.package_id != package_id
            or str(source.artifact_version) != artifact_version
            or stored_runtime.package_id != package_id
            or str(stored_runtime.artifact_version) != artifact_version
        ):
            raise KnowledgeArtifactStorageError(
                "stored artifact identity does not match its path"
            )
        if stored_manifest.runtime_sha256 != stored_runtime.sha256:
            raise KnowledgeArtifactStorageError(
                "stored runtime SHA-256 does not match manifest"
            )

        return (
            StoredKnowledgeArtifact(
                package_id=package_id,
                artifact_version=artifact_version,
                source_sha256=expected_checksums["source_sha256"],
                runtime_sha256=stored_runtime.sha256,
                manifest_sha256=expected_checksums["manifest_sha256"],
                release_path=str(release_path),
            ),
            stored_runtime,
        )

    def load(self, package_id: str, artifact_version: str) -> StoredKnowledgeArtifact:
        stored, _ = self._load_verified(package_id, artifact_version)
        return stored

    def load_active_runtime(
        self,
        package_id: str,
        artifact_version: str,
        *,
        active_release: ActiveKnowledgeRuntimeV1_1 | object,
        validation_report: ProductionValidationReportV1_1 | object,
    ) -> ActiveKnowledgeRuntimeV1_1:
        try:
            active = ActiveKnowledgeRuntimeV1_1.model_validate(active_release)
            report = ProductionValidationReportV1_1.model_validate(validation_report)
        except ValidationError as exc:
            raise KnowledgeArtifactStorageError(
                "Knowledge Library v1.1 ACTIVE evidence is missing or invalid"
            ) from exc

        if active.package_id != package_id or str(active.artifact_version) != artifact_version:
            raise KnowledgeArtifactStorageError(
                "ACTIVE release identity does not match the explicitly selected release"
            )

        _, stored_runtime = self._load_verified(package_id, artifact_version)
        if active.runtime_sha256 != stored_runtime.sha256:
            raise KnowledgeArtifactStorageError(
                "ACTIVE release runtime SHA-256 does not match the durable runtime"
            )
        if active.compiled_runtime != stored_runtime:
            raise KnowledgeArtifactStorageError(
                "ACTIVE release compiled runtime does not match the durable runtime"
            )

        try:
            validate_for_production_v1_1(stored_runtime, report)
        except KnowledgeActivationError as exc:
            raise KnowledgeArtifactStorageError(
                "production validation report does not approve the durable v1.1 runtime"
            ) from exc
        if active.validation_report_sha256 != report.sha256:
            raise KnowledgeArtifactStorageError(
                "ACTIVE release validation report SHA-256 does not match the supplied report"
            )

        return ActiveKnowledgeRuntimeV1_1(
            package_id=package_id,
            artifact_version=artifact_version,
            runtime_sha256=stored_runtime.sha256,
            validation_report_sha256=report.sha256,
            compiled_runtime=stored_runtime,
        )
