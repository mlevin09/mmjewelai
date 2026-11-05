"""Fetch an exact private preprod artifact; never print credentials or payloads."""

import hashlib
import json
import os
import re
import stat
import subprocess
import zipfile
from pathlib import Path


def validate_config(config):
    patterns = {
        "package_id": r"[a-z][a-z0-9_.-]+",
        "artifact_version": r"[0-9]+\.[0-9]+\.[0-9]+",
        "contract_version": r"1\.1\.0",
        "runtime_sha256": r"[0-9a-f]{64}",
        "validation_report_sha256": r"[0-9a-f]{64}",
        "object_sha256": r"[0-9a-f]{64}",
        "object_generation": r"[1-9][0-9]*",
        "object": r"gs://mmjewellai-preprod-tfstate/knowledge-releases/preprod/[A-Za-z0-9_./-]+\.zip",
    }
    if (
        not isinstance(config, dict)
        or set(config) != set(patterns)
        or any(
            not isinstance(config[key], str) or not re.fullmatch(pattern, config[key])
            for key, pattern in patterns.items()
        )
        or ".." in config["object"].split("/")
    ):
        raise ValueError("Invalid exact preprod Knowledge release configuration")


def unpack(archive, destination, config):
    validate_config(config)
    if destination.exists():
        raise ValueError("Knowledge destination must be new")
    if archive.stat().st_size > 10 * 1024 * 1024 or (
        hashlib.sha256(archive.read_bytes()).hexdigest() != config["object_sha256"]
    ):
        raise ValueError("Knowledge archive checksum mismatch")
    prefix = f"knowledge/{config['package_id']}/{config['artifact_version']}/"
    allowed = {"active.json", "validation-report.json", "integration-manifest.json"} | {
        prefix + f for f in ("source.json", "runtime.json", "manifest.json", "checksums.json")
    }
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        names = [e.filename for e in entries]
        if (
            len(names) != len(set(names))
            or set(names) != allowed
            or sum(e.file_size for e in entries) > 10 * 1024 * 1024
            or any(stat.S_ISLNK(e.external_attr >> 16) for e in entries)
        ):
            raise ValueError("Unexpected Knowledge archive members")
        manifest = json.loads(zipped.read("integration-manifest.json"))
        semantic = manifest["semantic"]
        if (
            any(
                semantic[k] != config[k]
                for k in ("package_id", "artifact_version", "contract_version", "runtime_sha256")
            )
            or semantic["production_validation_report_sha256"] != config["validation_report_sha256"]
        ):
            raise ValueError("Configured Knowledge identity mismatch")
        destination.mkdir()
        for entry in entries:
            path = destination / entry.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(zipped.read(entry))


def fetch(config, state_bucket):
    validate_config(config)
    if state_bucket != "mmjewellai-preprod-tfstate":
        raise ValueError("Wrong preprod state bucket")
    if not re.fullmatch(
        r"gs://mmjewellai-preprod-tfstate/knowledge-releases/preprod/[A-Za-z0-9_./-]+\.zip",
        config["object"],
    ) or ".." in config["object"].split("/"):
        raise ValueError("Knowledge archive must be in the private preprod release prefix")

    def generation():
        return subprocess.check_output(
            [
                "gcloud",
                "storage",
                "objects",
                "describe",
                config["object"],
                "--format=value(generation)",
            ],
            text=True,
        ).strip()

    if generation() != config["object_generation"]:
        raise ValueError("Knowledge object generation mismatch")
    archive = Path(".preprod-knowledge-release.zip")
    subprocess.run(["gcloud", "storage", "cp", config["object"], str(archive)], check=True)
    if generation() != config["object_generation"]:
        raise ValueError("Knowledge object changed during download")
    unpack(archive, Path(".preprod-knowledge-release"), config)


if __name__ == "__main__":
    fetch(
        json.loads(os.environ["TF_VAR_prompt_enrichment_release_json"]), os.environ["STATE_BUCKET"]
    )
