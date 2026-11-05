"""Archive/identity safety controls. Tiny payloads test transport, not qualification."""

import hashlib
import importlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest
from test_professional_knowledge_http import real_config as real_config

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/knowledge"))
transport = importlib.import_module("fetch_preprod_release")
verifier = importlib.import_module("verify_preprod_integration")


def archive(tmp_path, *, extra=None, semantic_hash="a" * 64):
    config = dict(
        package_id="jewelai.test.transport",
        artifact_version="1.0.0",
        contract_version="1.1.0",
        runtime_sha256="a" * 64,
        validation_report_sha256="b" * 64,
        object_generation="1",
        object="gs://mmjewellai-preprod-tfstate/knowledge-releases/preprod/test.zip",
    )
    semantic = {
        k: config[k]
        for k in ("package_id", "artifact_version", "contract_version", "runtime_sha256")
    }
    semantic["runtime_sha256"] = semantic_hash
    semantic["production_validation_report_sha256"] = config["validation_report_sha256"]
    path = tmp_path / "input.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("integration-manifest.json", json.dumps(dict(semantic=semantic)))
        for name in ("active.json", "validation-report.json"):
            z.writestr(name, "{}")
        for name in ("source.json", "runtime.json", "manifest.json", "checksums.json"):
            z.writestr("knowledge/jewelai.test.transport/1.0.0/" + name, "{}")
        if extra:
            z.writestr(extra, "not a release")
    config["object_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, config


def test_archive_exact_members_and_no_overwrite(tmp_path):
    path, config = archive(tmp_path)
    destination = tmp_path / "unpacked"
    transport.unpack(path, destination, config)
    assert len([p for p in destination.rglob("*") if p.is_file()]) == 7
    with pytest.raises(ValueError, match="must be new"):
        transport.unpack(path, destination, config)


@pytest.mark.parametrize("fault", ["checksum", "identity", "traversal", "extra", "config_path"])
def test_archive_fails_closed_before_extraction(tmp_path, fault):
    path, config = archive(
        tmp_path,
        extra={"traversal": "../escaped", "extra": "unknown"}.get(fault),
        semantic_hash="c" * 64 if fault == "identity" else "a" * 64,
    )
    if fault == "checksum":
        config["object_sha256"] = "0" * 64
    if fault == "config_path":
        config["package_id"] = "../../outside"
    with pytest.raises(ValueError):
        transport.unpack(path, tmp_path / "out", config)
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "escaped").exists()


def test_generation_bound_download_and_preprod_scope(tmp_path, monkeypatch):
    path, config = archive(tmp_path)
    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(transport.subprocess, "check_output", lambda *a, **k: "1\n")

    def download(command, **kwargs):
        calls.append(command)
        shutil.copyfile(path, tmp_path / ".preprod-knowledge-release.zip")

    monkeypatch.setattr(transport.subprocess, "run", download)
    with pytest.raises(ValueError, match="Wrong preprod"):
        transport.fetch(config, "production")
    assert calls == []
    transport.fetch(config, "mmjewellai-preprod-tfstate")
    assert len(calls) == 1
    assert (tmp_path / ".preprod-knowledge-release/active.json").exists()


def test_changed_generation_during_download_rejected(tmp_path, monkeypatch):
    path, config = archive(tmp_path)
    monkeypatch.chdir(tmp_path)
    values = iter(["1\n", "2\n"])
    monkeypatch.setattr(transport.subprocess, "check_output", lambda *a, **k: next(values))
    monkeypatch.setattr(
        transport.subprocess,
        "run",
        lambda *a, **k: shutil.copyfile(path, tmp_path / ".preprod-knowledge-release.zip"),
    )
    with pytest.raises(ValueError, match="changed during"):
        transport.fetch(config, "mmjewellai-preprod-tfstate")
    assert not (tmp_path / ".preprod-knowledge-release").exists()


def test_real_release_verifier_and_mismatched_consumers(real_config):
    from jewelai_api.artifacts import load_runtime_artifacts
    from jewelai_api.settings import ArtifactVersions

    preparation = importlib.import_module("prepare_preprod_integration")
    root = real_config.active_release_path.parent
    shutil.copyfile(real_config.validation_report_path, root / "validation-report.json")
    report = json.loads(real_config.validation_report_path.read_bytes())
    from jewelai_domain.knowledge_activation_v1_1 import ProductionValidationReportV1_1

    artifacts = load_runtime_artifacts(ROOT, ArtifactVersions(questions="2.0.0", rules="2.0.0"))
    manifest = dict(
        semantic={
            **{
                k: report[k]
                for k in ("package_id", "artifact_version", "contract_version", "runtime_sha256")
            },
            "production_validation_report_sha256": ProductionValidationReportV1_1.model_validate(
                report
            ).sha256,
        },
        versions=vars(artifacts.versions),
        parametric={"typed_runtime_sha256": artifacts.parametric_knowledge.sha256},
        consumer_artifacts=[dict(name=k, file_sha256=v) for k, v in artifacts.artifact_hashes],
        recovered_components={
            k: dict(
                path=relative,
                file_sha256=hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
            )
            for k, (relative, _) in preparation.RECOVERED_COMPONENTS.items()
        },
    )
    (root / "integration-manifest.json").write_text(json.dumps(manifest))
    assert verifier.verify(root, ROOT).status == "QUALIFIED"
    manifest["parametric"]["typed_runtime_sha256"] = "0" * 64
    (root / "integration-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Parametric"):
        verifier.verify(root, ROOT)
