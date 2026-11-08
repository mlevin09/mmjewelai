"""Immutable, local-only model bundle validation (before importing inference libraries)."""

import hashlib
import json
from pathlib import Path

MODEL_ID = "Qwen/Qwen3-ASR-1.7B"
REVISION = "7278e1e70fe206f11671096ffdd38061171dd6e5"
WEIGHTS = {
    "model-00001-of-00002.safetensors": (
        "a4cd1f1a04d90b757dc7f7dd26254e69a013b19e80efe590a83c6a3bde8608d6"
    ),
    "model-00002-of-00002.safetensors": (
        "6e0b9d9e09e2e0238e7ef3cc8a484ab387e91b90f1900bedf88bc92d7929ccfc"
    ),
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
