"""Immutable, local-only model bundle validation (before importing inference libraries)."""

import hashlib
import json
from pathlib import Path

MODEL_ID = "Systran/faster-whisper-small"
REVISION = "536b0662742c02347bc0e980a01041f333bce120"
WEIGHTS = {
    "model.bin": "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671",
}


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_artifacts(root: Path, *, weights: dict[str, str] = WEIGHTS) -> None:
    """The container digest binds the manifest; its entries bind every local artifact."""
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["model_id"] != MODEL_ID or manifest["revision"] != REVISION:
        raise ValueError("invalid_model_bundle")
    files = manifest["files"]
    actual = {p.name for p in root.iterdir() if p.name != "manifest.json"}
    if not isinstance(files, dict) or set(files) != actual or not weights.keys() <= files.keys():
        raise ValueError("invalid_model_bundle")
    for name, digest in files.items():
        path = root / name
        if Path(name).name != name or path.is_symlink() or not path.is_file():
            raise ValueError("invalid_model_bundle")
        if file_sha256(path) != digest or (name in weights and digest != weights[name]):
            raise ValueError("invalid_model_bundle")
