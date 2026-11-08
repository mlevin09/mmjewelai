"""BUILD ONLY: acquire a pinned public snapshot, then bind all files by SHA-256."""

import json
import shutil
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

from jewelai_stt.artifacts import MODEL_ID, REVISION, WEIGHTS, file_sha256, verify_artifacts


def main(destination: Path) -> None:
    if destination.exists():
        raise SystemExit("model destination must not exist")
    # This command must run only in the controlled network-enabled build stage.
    source = Path(snapshot_download(repo_id=MODEL_ID, revision=REVISION))
    destination.mkdir()
    for path in sorted(source.iterdir()):
        if path.is_file() and not path.name.startswith("."):
            shutil.copyfile(path, destination / path.name)
    files = {p.name: file_sha256(p) for p in sorted(destination.iterdir())}
    if any(files.get(name) != digest for name, digest in WEIGHTS.items()):
        raise SystemExit("model weight checksum mismatch")
    manifest = {"model_id": MODEL_ID, "revision": REVISION, "files": files}
    (destination / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    )
    verify_artifacts(destination)
    print("model_manifest_sha256=" + file_sha256(destination / "manifest.json"))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
