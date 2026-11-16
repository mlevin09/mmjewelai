"""Rebind consumer hashes without republishing or promoting semantic Knowledge.

Input is an exact generation/SHA-pinned existing private archive. Only its
operational integration manifest changes; all six qualification/store files
retain their original bytes. The existing image verifier remains authoritative.
"""

import argparse
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

from fetch_preprod_release import unpack
from jewelai_api.artifacts import load_runtime_artifacts
from jewelai_api.settings import ArtifactVersions
from verify_preprod_integration import verify


def rebind(archive: Path, config: dict, output: Path, repository_root: Path):
    """Validate everything before publishing a new, deterministic archive."""
    if output.exists():
        raise ValueError("Output archive must be new")
    with tempfile.TemporaryDirectory() as temporary:
        release = Path(temporary) / "release"
        # Reuse exact member, checksum, path and semantic selection validation.
        unpack(archive, release, config)
        path = release / "integration-manifest.json"
        manifest = json.loads(path.read_bytes())
        artifacts = load_runtime_artifacts(
            repository_root, ArtifactVersions(**manifest["versions"])
        )
        # Keep every other field, including recovered identities, typed runtime,
        # original provenance, semantic hashes, versions and explicit gaps.
        manifest["consumer_artifacts"] = [
            dict(name=name, file_sha256=value) for name, value in artifacts.artifact_hashes
        ]
        path.write_bytes(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
            + b"\n"
        )
        # This loads/recompiles the actual store and checks ACTIVE/report binding,
        # all consumers and recovered components. No activation is performed.
        verify(release, repository_root)
        with output.open("xb") as stream, zipfile.ZipFile(stream, "w") as destination:
            for member in sorted(p for p in release.rglob("*") if p.is_file()):
                info = zipfile.ZipInfo(member.relative_to(release).as_posix())
                info.create_system = 3
                info.external_attr = 0o100444 << 16
                destination.writestr(
                    info, member.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9
                )
    return {"object_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            rebind(
                args.archive,
                json.loads(args.config.read_bytes()),
                args.output,
                args.repository_root,
            ),
            sort_keys=True,
        )
    )
