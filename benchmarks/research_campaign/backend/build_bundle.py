"""Build an allowlisted, secret-free backend snapshot. Does not contact GCP/OpenAI."""

import argparse
import gzip
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = {
    "jewelai_research": (
        ROOT / "research_campaign/src/jewelai_research",
        ("__init__", "backend", "vm_access", "contracts", "leases", "lifecycle", "owned_lifecycle"),
    ),
    "native_llm_bench": (
        ROOT / "native_llm_stage1/src/native_llm_bench",
        ("__init__", "contracts", "storage", "transport", "instructions"),
    ),
}


def build(output):
    files = {
        package + "/" + name + ".py": (root / (name + ".py")).read_bytes()
        for package, (root, names) in PACKAGES.items()
        for name in names
    }
    manifest = {
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "files": {k: hashlib.sha256(v).hexdigest() for k, v in sorted(files.items())},
    }
    files["manifest.json"] = json.dumps(manifest, sort_keys=True).encode()
    with Path(output).open("wb") as sink, gzip.GzipFile(fileobj=sink, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            for name, data in sorted(files.items()):
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(data), 0o644, 0
                tar.addfile(info, io.BytesIO(data))
    return hashlib.sha256(Path(output).read_bytes()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    print(build(parser.parse_args().output))
