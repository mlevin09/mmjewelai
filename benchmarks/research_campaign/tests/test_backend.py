import importlib.util
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from native_llm_bench.contracts import InvalidArtifact, digest

from jewelai_research.backend import BackendAccess, ManagedSecrets, prepare, run_tunnel
from jewelai_research.contracts import TARGET
from jewelai_research.vm_access import AccessLease, serve

BACKEND = Path(__file__).parents[1] / "backend"


class Secrets:
    def __init__(self):
        self.revoked = False
        self.calls = []

    def read(self, name):
        self.calls.append(name)
        if self.revoked:
            raise InvalidArtifact("managed_credential_unavailable")
        return {
            "tunnel": b"synthetic-private-runtime-credential",
            "ssh": b"synthetic-private-ssh-credential",
            "authorization": b'{"approved":false}',
        }[name]


@pytest.fixture
def configuration(tmp_path):
    return {
        "gcloud": "/usr/bin/gcloud",
        "client": "/opt/tunnel-client",
        "runtime": str(tmp_path / "run"),
        "state": str(tmp_path / "persistent"),
        "known_hosts": "/etc/jewelai-research/known_hosts",
        "tunnel_id": "tunnel_" + "a" * 32,
    }


def test_backend_tunnel_composition_restart_preserves_lease_without_mac(configuration):
    secrets = Secrets()
    access = prepare(configuration, secrets)
    lease = AccessLease(access["state"], access["authorization"])
    lease._save({"lease_id": "owned", "phase": "STOP_INTENT"})
    calls = []

    def client(args, **kwargs):
        calls.append(args)
        if args[1] == "init":
            assert "--force" in args
            assert "-m jewelai_research.backend serve" in args[args.index("--mcp-command") + 1]
        assert not any(b"synthetic-private" in str(s).encode() for s in args)
        assert not any("/Users/" in s or "Application Support" in s for s in args)
        return SimpleNamespace(returncode=0)

    # Process restart: reconnect using the same profile and persistent state, not a start RPC.
    for _ in range(2):
        run_tunnel(configuration, secrets, "/etc/jewelai-research/backend.json", run=client)
    assert [a[1] for a in calls] == ["init", "doctor", "run"] * 2
    assert lease.read()["phase"] == "STOP_INTENT"
    assert not any("instances" in arg for call in calls for arg in call)
    assert os.stat(access["authorization"]).st_mode & 0o077 == 0
    assert (Path(configuration["runtime"]) / "tunnel-key").stat().st_mode & 0o077 == 0


def test_actual_stdio_handler_exposes_seven_tools_and_stopped_status(configuration):
    secrets = Secrets()
    access = BackendAccess(prepare(configuration, secrets), secrets)
    access.cloud.inspect = lambda: {"status": "TERMINATED"}
    requests = [
        {"id": 1, "method": "tools/list"},
        {"id": 2, "method": "tools/call", "params": {"name": "vm_status", "arguments": {}}},
    ]
    source = io.StringIO("\n".join(json.dumps({"jsonrpc": "2.0", **r}) for r in requests))
    output = io.StringIO()
    serve(access, source, output)
    first, second = [json.loads(line) for line in output.getvalue().splitlines()]
    assert {t["name"] for t in first["result"]["tools"]} == {
        "vm_status",
        "vm_start",
        "vm_stop",
        "vm_exec",
        "vm_job",
        "vm_read",
        "vm_write",
    }
    assert second["result"]["structuredContent"]["status"] == "TERMINATED"


def test_disabled_managed_activation_denies_start(configuration):
    secrets = Secrets()
    access = BackendAccess(prepare(configuration, secrets), secrets)
    access.cloud.inspect = lambda: pytest.fail("no paid cloud operation")
    with pytest.raises(InvalidArtifact, match="owner_start_authorization_required"):
        access.call("vm_start", {})


@pytest.mark.parametrize("returncode,stdout", [(1, b"private provider payload"), (0, b"")])
def test_managed_credentials_fail_closed_without_cli_payload(returncode, stdout):
    def run(args, **kwargs):
        assert args[1:5] == ["secrets", "versions", "access", "latest"]
        assert "--project=mmjewellai-preprod" in args
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=b"secret message")

    with pytest.raises(InvalidArtifact, match="^managed_credential_unavailable$"):
        ManagedSecrets("gcloud", run=run).read("tunnel")


def test_revocation_blocks_a_previously_prepared_connection(configuration):
    secrets = Secrets()
    access = BackendAccess(prepare(configuration, secrets), secrets)
    secrets.revoked = True
    access.cloud.inspect = lambda: pytest.fail("revoked access must not reach GCP")
    with pytest.raises(InvalidArtifact, match="managed_credential_unavailable"):
        access.call("vm_status", {})


def test_tunnel_interruption_never_retries_or_starts_vm(configuration):
    calls = []

    def client(args, **kwargs):
        calls.append(args[1])
        return SimpleNamespace(returncode=1 if args[1] == "run" else 0)

    with pytest.raises(InvalidArtifact, match="private_tunnel_disconnected"):
        run_tunnel(configuration, Secrets(), "/etc/backend.json", run=client)
    assert calls == ["init", "doctor", "run"]


def test_restart_preserves_consumed_authorization_and_uncertain_ownership(tmp_path):
    import time

    authorization = tmp_path / "approval.json"
    approved = {
        "target": TARGET,
        "approved": True,
        "expires_at": int(time.time()) + 600,
        "maximum_starts": 1,
    }
    authorization.write_text(json.dumps(approved))
    root = tmp_path / "state"
    lease = AccessLease(root, authorization)
    first = lease.begin({})
    lease.record(first["lease_id"], "START_INTENT", instance_id="123")
    # A connection/host loss in the ambiguous RPC window cannot create another start.
    restored = AccessLease(root, authorization)
    with pytest.raises(InvalidArtifact, match="ownership_blocked"):
        restored.begin({})
    restored.record(first["lease_id"], "RELEASED")
    with pytest.raises(InvalidArtifact, match="authorized_start_count_exhausted"):
        AccessLease(root, authorization).begin({})
    # A different explicit Owner-approved window has its own count, not a global reset.
    approved["expires_at"] += 1
    authorization.write_text(json.dumps(approved))
    AccessLease(root, authorization).begin({})
    assert len(list(root.glob("*.start"))) == 2


def test_no_mcp_credential_payload_in_errors(configuration):
    secrets = Secrets()
    access = BackendAccess(prepare(configuration, secrets), secrets)
    secrets.revoked = True
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "vm_start", "arguments": {}},
    }
    output = io.StringIO()
    serve(access, io.StringIO(json.dumps(request)), output)
    assert json.loads(output.getvalue())["error"]["message"] == "vm_access_blocked"
    assert "credential" not in output.getvalue()


def test_backend_bundle_contains_only_required_runtime_and_matches_manifest(tmp_path):
    spec = importlib.util.spec_from_file_location("bundle", BACKEND / "build_bundle.py")
    bundle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bundle)
    path = tmp_path / "bundle.tar.gz"
    first = bundle.build(path)
    assert bundle.build(path) == first
    with tarfile.open(path) as tar:
        names = tar.getnames()
        manifest = json.load(tar.extractfile("manifest.json"))
        assert set(names) == {*manifest["files"], "manifest.json"}
        assert not any(s in name for name in names for s in ("controller", "worker", "fixtures"))
        import hashlib

        for name, sha in manifest["files"].items():
            assert hashlib.sha256(tar.extractfile(name).read()).hexdigest() == sha


def test_systemd_supervision_and_no_public_endpoint():
    unit = (BACKEND / "jewelai-research-connection.service").read_text()
    assert "Restart=always" in unit and "WantedBy=multi-user.target" in unit
    assert "StateDirectoryMode=0700" in unit and "RuntimeDirectoryMode=0700" in unit
    assert "User=jewelai-mcp" in unit and "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit and "StandardError=null" in unit
    tf = (BACKEND / "terraform/main.tf").read_text()
    assert "access_config" not in tf
    assert 'source_ranges = ["35.235.240.0/20"]' in tf
    assert "google_secret_manager_secret_version" not in tf
    assert "instance_name = local.target" in tf
    assert "setMetadata" not in tf
    assert "0.0.0.0/0" not in tf


def test_lease_hash_integrity_survives_backend_restart(configuration):
    secrets = Secrets()
    access = prepare(configuration, secrets)
    lease = AccessLease(access["state"], access["authorization"])
    original = lease._save({"phase": "OWNED", "lease_id": "example"})
    prepare(configuration, secrets)
    assert AccessLease(access["state"], access["authorization"]).read() == original
    path = Path(access["state"]) / "lease.json"
    path.write_text(json.dumps({"lease": {"phase": "RELEASED"}, "sha256": digest(original)}))
    with pytest.raises(InvalidArtifact, match="lease_integrity"):
        AccessLease(access["state"], access["authorization"]).read()


@pytest.mark.parametrize(
    "args",
    [
        ["--configure", "not-a-tunnel"],
        ["--stage", "bundle", "bad-sha", "hosts"],
        ["--configure"],
        ["--configure", "tunnel_bad;false"],
    ],
)
def test_installer_rejects_invalid_staging_and_configuration_before_changes(tmp_path, args):
    # Only bypass the root guard; each invalid argument must exit before any install,
    # service command or write. No Linux provisioning is simulated as a live result.
    stub = tmp_path / "id"
    stub.write_text('#!/bin/sh\nprintf "0\\n"\n')
    stub.chmod(0o755)
    result = subprocess.run(
        ["bash", str(BACKEND / "install.sh"), *args],
        env={**os.environ, "PATH": str(tmp_path) + ":" + os.environ["PATH"]},
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
