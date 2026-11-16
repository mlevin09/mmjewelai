"""Consumer-only rebinding of the existing qualified seven-file archive."""

import hashlib
import importlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest
from test_professional_knowledge_http import real_config as real_config
from tests.current_roles import current_roles

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/knowledge"))
transport = importlib.import_module("fetch_preprod_release")
verifier = importlib.import_module("verify_preprod_integration")
rebinder = importlib.import_module("rebind_preprod_integration")


def verified_release(real_config):
    from jewelai_api.artifacts import load_runtime_artifacts
    from jewelai_api.settings import ArtifactVersions

    preparation = importlib.import_module("prepare_preprod_integration")
    root = real_config.active_release_path.parent
    shutil.copyfile(real_config.validation_report_path, root / "validation-report.json")
    report = json.loads(real_config.validation_report_path.read_bytes())
    from jewelai_domain.knowledge_activation_v1_1 import ProductionValidationReportV1_1

    artifacts = load_runtime_artifacts(
        ROOT, ArtifactVersions(questions="2.0.0", rules="2.0.0"), roles=current_roles()
    )
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
    return root, manifest


def old_consumer_archive(real_config, tmp_path, *, fault=None):
    root, manifest = verified_release(real_config)
    # Authentic qualification fixture, stale consumers as in the failed overlay.
    for row in manifest["consumer_artifacts"]:
        if row["name"] == "questions":
            row["file_sha256"] = "0" * 64
    manifest["consumer_artifacts"].append(dict(name="roles", file_sha256="1" * 64))
    if fault == "recovered":
        manifest["recovered_components"]["dictionary"]["file_sha256"] = "0" * 64
    if fault == "parametric":
        manifest["parametric"]["typed_runtime_sha256"] = "0" * 64
    (root / "integration-manifest.json").write_text(json.dumps(manifest))
    if fault in {"active", "report", "runtime"}:
        path = {
            "active": root / "active.json",
            "report": root / "validation-report.json",
            "runtime": next((root / "knowledge").rglob("runtime.json")),
        }[fault]
        payload = json.loads(path.read_bytes())
        payload["runtime_sha256"] = "0" * 64
        path.write_text(json.dumps(payload))
    path = tmp_path / "qualified-old.zip"
    members = sorted(p for p in root.rglob("*") if p.is_file())
    with zipfile.ZipFile(path, "w") as z:
        for member in members:
            z.write(member, member.relative_to(root).as_posix())
    semantic = manifest["semantic"]
    config = {
        k: semantic[k]
        for k in ("package_id", "artifact_version", "contract_version", "runtime_sha256")
    }
    config.update(
        validation_report_sha256=semantic["production_validation_report_sha256"],
        object="gs://mmjewellai-preprod-tfstate/knowledge-releases/preprod/test.zip",
        object_generation="1",
        object_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    return path, config, manifest


def test_rebind_preserves_all_qualified_bytes_and_metadata(real_config, tmp_path):
    path, config, original = old_consumer_archive(real_config, tmp_path)
    original_bytes = path.read_bytes()
    transport.unpack(path, tmp_path / "old", config)
    with pytest.raises(ValueError, match="Consumer artifact bytes"):
        verifier.verify(tmp_path / "old", ROOT)
    output = tmp_path / "new.zip"
    receipt = rebinder.rebind(path, config, output, ROOT)
    second = tmp_path / "second.zip"
    assert rebinder.rebind(path, config, second, ROOT) == receipt
    assert second.read_bytes() == output.read_bytes()
    assert path.read_bytes() == original_bytes
    with zipfile.ZipFile(path) as before, zipfile.ZipFile(output) as after:
        assert set(before.namelist()) == set(after.namelist())
        assert len(after.namelist()) == 7
        for name in before.namelist():
            if name != "integration-manifest.json":
                assert before.read(name) == after.read(name)
        current = json.loads(after.read("integration-manifest.json"))
        assert {k: v for k, v in original.items() if k != "consumer_artifacts"} == {
            k: v for k, v in current.items() if k != "consumer_artifacts"
        }
        assert all(row["name"] != "roles" for row in current["consumer_artifacts"])
    transport.unpack(output, tmp_path / "new", {**config, **receipt})
    assert verifier.verify(tmp_path / "new", ROOT).status == "QUALIFIED"
    with pytest.raises(ValueError, match="must be new"):
        rebinder.rebind(path, config, output, ROOT)
    assert second.read_bytes() == output.read_bytes()


@pytest.mark.parametrize(
    "fault", ["checksum", "active", "report", "runtime", "recovered", "parametric"]
)
def test_rebind_refuses_invalid_original_evidence(real_config, tmp_path, fault):
    path, config, _ = old_consumer_archive(real_config, tmp_path, fault=fault)
    if fault == "checksum":
        config["object_sha256"] = "0" * 64
    output = tmp_path / "not-published.zip"
    with pytest.raises(ValueError):
        rebinder.rebind(path, config, output, ROOT)
    assert not output.exists()


@pytest.mark.parametrize("fault", ["manifest", "consumer"])
def test_rebound_overlay_still_rejects_tampering(real_config, tmp_path, fault):
    path, config, _ = old_consumer_archive(real_config, tmp_path)
    output = tmp_path / "new.zip"
    receipt = rebinder.rebind(path, config, output, ROOT)
    release = tmp_path / "new"
    transport.unpack(output, release, {**config, **receipt})
    repository = ROOT
    if fault == "manifest":
        manifest_path = release / "integration-manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["consumer_artifacts"][0]["file_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest))
    else:
        repository = tmp_path / "repository"
        shutil.copytree(ROOT / "data", repository / "data")
        consumer = repository / "data/questions/v2.0.0.json"
        consumer.write_bytes(consumer.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Consumer artifact bytes"):
        verifier.verify(release, repository)


def test_roles_release_pin_preserves_qualified_semantic_selection(real_config):
    from jewelai_domain.knowledge_activation_v1_1 import ProductionValidationReportV1_1

    config = json.loads(
        (ROOT / "docs/prompt-enrichment/preprod-knowledge/roles-001-release-pin.json").read_bytes()
    )
    transport.validate_config(config)
    report = ProductionValidationReportV1_1.model_validate_json(
        real_config.validation_report_path.read_bytes()
    )
    assert config["runtime_sha256"] == report.runtime_sha256
    assert config["validation_report_sha256"] == report.sha256
    assert config["package_id"] == report.package_id
    assert config["artifact_version"] == str(report.artifact_version)
    assert config["contract_version"] == report.contract_version
    assert config["object"].endswith(f"/{config['runtime_sha256']}/{config['object_sha256']}.zip")
