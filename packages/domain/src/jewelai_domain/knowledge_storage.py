"""Immutable filesystem storage for versioned Knowledge Library artifacts."""

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

from pydantic import ValidationError

from .knowledge_activation import (
    ActiveKnowledgeRuntime,
    KnowledgeActivationError,
    ProductionValidationReport,
    validate_for_production,
)
from .knowledge_library import (
    CompilationManifest,
    CompiledKnowledgeLibrary,
    KnowledgeLibraryBundle,
    compile_knowledge_library,
    validate_knowledge_library,
)
from .models import ImmutableModel


class KnowledgeArtifactStorageError(ValueError):
    """Raised when a durable artifact is missing, mutable, or fails integrity checks."""


class StoredKnowledgeArtifact(ImmutableModel):
    package_id: str
    artifact_version: str
    source_sha256: str
    runtime_sha256: str
    manifest_sha256: str
    release_path: str


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class KnowledgeArtifactStore:
    """Content-verified immutable storage rooted at an explicitly configured path.

    The store is provider-neutral. The root may be a checked-in artifact directory, a mounted
    durable volume, or a directory synchronized by an external delivery mechanism. Publishing the
    same package/version is idempotent only when every canonical artifact is byte-identical.
    """

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
        bundle: KnowledgeLibraryBundle,
    ) -> tuple[dict[str, str], CompiledKnowledgeLibrary]:
        registry = validate_knowledge_library(bundle)
        runtime, manifest = compile_knowledge_library(registry)
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
            raise KnowledgeArtifactStorageError(f"artifact path is not a directory: {release_path}")
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

    def publish(self, bundle: KnowledgeLibraryBundle | object) -> StoredKnowledgeArtifact:
        """Compile and atomically publish one immutable package/version."""

        validated = validate_knowledge_library(bundle).bundle
        if validated.artifact_version is None:
            raise KnowledgeArtifactStorageError("artifact_version is required for durable storage")
        payloads, runtime = self._payloads(validated)
        version = str(validated.artifact_version)
        release_path = self._release_path(validated.package_id, version)

        if release_path.exists():
            self._verify_existing(release_path, payloads)
            return self.load(validated.package_id, version)

        release_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{version}-", dir=str(release_path.parent)))
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
    ) -> tuple[StoredKnowledgeArtifact, CompiledKnowledgeLibrary]:
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
            source = KnowledgeLibraryBundle.model_validate_json(raw["source.json"])
            stored_runtime = CompiledKnowledgeLibrary.model_validate_json(raw["runtime.json"])
            stored_manifest = CompilationManifest.model_validate_json(raw["manifest.json"])
            checksums = json.loads(raw["checksums.json"])
        except (ValidationError, json.JSONDecodeError) as exc:
            raise KnowledgeArtifactStorageError("stored knowledge artifact is invalid") from exc

        expected_runtime, expected_manifest = compile_knowledge_library(source)
        expected_checksums = {
            "source_sha256": _sha256(raw["source.json"]),
            "runtime_sha256": _sha256(raw["runtime.json"]),
            "manifest_sha256": _sha256(raw["manifest.json"]),
        }
        if checksums != expected_checksums:
            raise KnowledgeArtifactStorageError("stored knowledge artifact checksum mismatch")
        if stored_runtime != expected_runtime:
            raise KnowledgeArtifactStorageError(
                "stored runtime does not match deterministic compiler"
            )
        if stored_manifest != expected_manifest:
            raise KnowledgeArtifactStorageError(
                "stored manifest does not match deterministic compiler"
            )
        if (
            source.package_id != package_id
            or str(source.artifact_version) != artifact_version
            or stored_runtime.package_id != package_id
            or str(stored_runtime.artifact_version) != artifact_version
        ):
            raise KnowledgeArtifactStorageError("stored artifact identity does not match its path")
        if stored_manifest.runtime_sha256 != stored_runtime.sha256:
            raise KnowledgeArtifactStorageError("stored runtime SHA-256 does not match manifest")

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
        """Load one stored release and verify source, compiler output, manifest, and checksums."""

        stored, _ = self._load_verified(package_id, artifact_version)
        return stored

    def load_active_runtime(
        self,
        package_id: str,
        artifact_version: str,
        *,
        active_release: ActiveKnowledgeRuntime | object,
        validation_report: ProductionValidationReport | object,
    ) -> ActiveKnowledgeRuntime:
        """Load one explicit durable release through its exact ACTIVE evidence.

        The caller selects the package and version and supplies the separately governed ACTIVE
        envelope and production-validation report. The returned envelope is rebuilt around the
        compiled runtime deserialized from the verified durable artifact, so an in-memory envelope
        can never substitute different runtime content for the selected release.
        """

        try:
            active = ActiveKnowledgeRuntime.model_validate(active_release)
        except ValidationError as exc:
            raise KnowledgeArtifactStorageError(
                "ACTIVE release envelope is missing or invalid"
            ) from exc
        try:
            report = ProductionValidationReport.model_validate(validation_report)
        except ValidationError as exc:
            raise KnowledgeArtifactStorageError(
                "production validation report is missing or invalid"
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
            validate_for_production(stored_runtime, report)
        except KnowledgeActivationError as exc:
            raise KnowledgeArtifactStorageError(
                "production validation report does not approve the durable runtime"
            ) from exc
        if active.validation_report_sha256 != report.sha256:
            raise KnowledgeArtifactStorageError(
                "ACTIVE release validation report SHA-256 does not match the supplied report"
            )

        return ActiveKnowledgeRuntime(
            package_id=package_id,
            artifact_version=artifact_version,
            runtime_sha256=stored_runtime.sha256,
            validation_report_sha256=report.sha256,
            compiled_runtime=stored_runtime,
        )
