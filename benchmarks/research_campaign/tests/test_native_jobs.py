"""Targeted connection tests; not live Workspace/Qwen acceptance."""

import base64
import importlib.util
import json
import shutil
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from native_llm_bench import storage
from native_llm_bench.contracts import InvalidArtifact, sha256_file
from starlette.testclient import TestClient
from test_https_gateway import oauth as oauth
from test_https_gateway import rpc

from jewelai_research import runner_guest
from jewelai_research.backend import NativeBackendAccess
from jewelai_research.contracts import TARGET, Inputs
from jewelai_research.https_gateway import create_app
from jewelai_research.native_jobs import EXECUTE_SCOPE, READ_SCOPE, TOOLS, NativeRunnerActions
from jewelai_research.synthetic import SyntheticTransport
from jewelai_research.vm_access import VmAccess

FIXTURES = Path(__file__).parents[2] / "native_llm_stage1/fixtures"


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    source, work = tmp_path / "source", tmp_path / "work"
    source.mkdir()
    work.mkdir()
    for name in ("runtime", "model"):
        shutil.copyfile(FIXTURES / f"synthetic.{name}.json", source / f"{name}.json")
    inputs = Inputs(source / "runtime.json", source / "model.json")
    approval = {
        "target": TARGET,
        "approved": True,
        "expires_at": int(time.time()) + 600,
        "maximum_starts": 1,
        "native_runner": {
            "maximum_jobs": 4,
            "maximum_turns": 10,
            "maximum_job_seconds": 200,
            "approved_usd": 1,
        },
    }
    path = tmp_path / "activation.json"
    storage.write(path, approval)
    ssh_key = tmp_path / "private-key"
    access = VmAccess(
        {
            "gcloud": "FAKE",
            "state": str(tmp_path / "state"),
            "authorization": str(path),
            "ssh_key": str(ssh_key),
            "known_hosts": "pinned",
            "guest_ready": True,
        }
    )
    monkeypatch.setattr(runner_guest, "SOURCE", source)
    monkeypatch.setattr(runner_guest, "WORK", work)
    launches, requests = [], []

    def guest(op, args):
        requests.append((op, args))
        return runner_guest.handle(op, args, launch=lambda *a, **kw: launches.append((a, kw)))

    access._guest = guest
    access.call = MagicMock(side_effect=AssertionError("no lifecycle operation expected"))
    paths = {"runtime": str(source / "runtime.json"), "manifest": str(source / "model.json")}
    actions = NativeRunnerActions(access, inputs, paths, guest_ready=True)
    principal = SimpleNamespace(subject="synthetic-owner", scopes=[READ_SCOPE, EXECUTE_SCOPE])
    args = {
        "idempotency_key": "research-1",
        "sessions": ["SYN2"],
        "parameters": {"temperature": 0.2},
        "hypothesis": "Synthetic: compare the controlled completion outcome.",
    }
    return SimpleNamespace(
        actions=actions,
        inputs=inputs,
        access=access,
        principal=principal,
        args=args,
        approval=approval,
        path=path,
        requests=requests,
        launches=launches,
        work=work,
        paths=paths,
    )


def test_existing_runner_job_result_then_agent_selected_followup_and_restart(bridge):
    b = bridge
    first = b.actions.call(b.principal, "native_runner_submit", b.args)
    jid = first["job_id"]
    assert first["status"] == "RUNNING" and len(b.launches) == 1
    assert b.actions.call(b.principal, "native_runner_submit", b.args) == first
    model = SyntheticTransport(truncate_control=False)
    result = runner_guest.run_job(jid, transport=model)
    assert result["status"] == "COMPLETED" and result["attempts"] == 2
    status = b.actions.call(b.principal, "native_runner_status", {"job_id": jid})
    assert status["plan_sha256"] == result["plan_sha256"]
    raw, offset = b"", 0
    while True:
        chunk = b.actions.call(
            b.principal, "native_runner_result", {"job_id": jid, "offset": offset}
        )
        raw += base64.b64decode(chunk["data_base64"])
        offset = chunk["next_offset"]
        if chunk["eof"]:
            break
    assert __import__("hashlib").sha256(raw).hexdigest() == result["export_sha256"]
    exported = json.loads(raw)
    assert exported["run"]["runner"]["source_sha256"] == b.inputs.runner_sha
    assert len(exported["attempt_results"]) == len(model.calls) == 2
    assert not any("evaluator" in payload for payload in model.calls)
    old_receipt = (b.work / ".native-runner" / jid / "receipt.json").read_bytes()
    restored = NativeRunnerActions(b.access, b.inputs, b.paths, guest_ready=True)
    assert restored.call(b.principal, "native_runner_status", {"job_id": jid}) == status
    followup = {
        **b.args,
        "idempotency_key": "research-2",
        "parameters": {"max_tokens": 256},
        "hypothesis": "Synthetic follow-up chosen by caller after reading the first result.",
    }
    second = restored.call(b.principal, "native_runner_submit", followup)
    assert second["job_id"] != jid and len(b.launches) == 2
    assert (b.work / ".native-runner" / jid / "receipt.json").read_bytes() == old_receipt
    b.access.call.assert_not_called()


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (
            {"parameters": {"endpoint": "https://attacker.test"}},
            "unsupported_native_runner_parameter",
        ),
        ({"parameters": {"command": "echo private"}}, "unsupported_native_runner_parameter"),
        ({"parameters": {"max_attempts": 3}}, "unsupported_native_runner_parameter"),
        ({"parameters": {"max_tokens": True}}, "invalid maximum tokens"),
        ({"sessions": ["KG09"]}, "native_runner_holdout_or_unknown_session"),
        ({"sessions": ["SYN2", "SYN2"]}, "invalid_native_runner_sessions"),
    ],
)
def test_untrusted_controls_never_reach_guest(bridge, mutation, reason):
    b = bridge
    with pytest.raises(InvalidArtifact, match=reason):
        b.actions.call(b.principal, "native_runner_submit", {**b.args, **mutation})
    assert not b.requests and not b.launches


def test_disabled_missing_or_expired_owner_approval_blocks_before_cloud(bridge):
    b = bridge
    for change in ({"approved": False}, {"expires_at": 1}, {"native_runner": None}):
        storage.write(b.path, {**b.approval, **change}, replace=True)
        with pytest.raises(InvalidArtifact):
            b.actions.call(b.principal, "native_runner_start", {})
        with pytest.raises(InvalidArtifact):
            b.actions.call(b.principal, "native_runner_submit", b.args)
    assert not b.requests
    b.access.call.assert_not_called()


def test_read_scope_cannot_execute_and_other_subject_cannot_read_results(bridge):
    b = bridge
    reader = SimpleNamespace(subject=b.principal.subject, scopes=[READ_SCOPE])
    for action, args in [
        ("native_runner_submit", b.args),
        ("native_runner_start", {}),
        ("native_runner_stop", {}),
    ]:
        with pytest.raises(InvalidArtifact, match="execution_scope_required"):
            b.actions.call(reader, action, args)
    first = b.actions.call(b.principal, "native_runner_submit", b.args)
    other = SimpleNamespace(subject="other-researcher", scopes=[READ_SCOPE])
    with pytest.raises(InvalidArtifact, match="native_job_not_found"):
        b.actions.call(other, "native_runner_status", {"job_id": first["job_id"]})


def test_ambiguous_dispatch_is_charged_and_never_reissued_after_restart(bridge):
    b = bridge
    guest = MagicMock(side_effect=TimeoutError("PRIVATE-SENTINEL"))
    b.access._guest = guest
    result = b.actions.call(b.principal, "native_runner_submit", b.args)
    assert result["status"] == "UNKNOWN" and "PRIVATE-SENTINEL" not in json.dumps(result)
    restored = NativeRunnerActions(b.access, b.inputs, b.paths, guest_ready=True)
    assert restored.call(b.principal, "native_runner_submit", b.args) == result
    guest.assert_called_once()
    changed = {**b.args, "parameters": {"temperature": 0.4}}
    with pytest.raises(InvalidArtifact, match="native_idempotency_conflict"):
        restored.call(b.principal, "native_runner_submit", changed)
    with b.actions.ledger.transaction() as db:
        events = b.actions.ledger.read(db, "native-runner")
    assert sum(e["kind"] == "RESERVED" for e in events) == 1
    with pytest.raises(InvalidArtifact, match="already_busy"):
        restored.call(b.principal, "native_runner_submit", {**b.args, "idempotency_key": "second"})


@pytest.mark.parametrize("limit,value", [("maximum_jobs", 1), ("maximum_turns", 2)])
def test_actual_budget_exhaustion_including_unknown_is_durable(bridge, limit, value):
    b = bridge
    b.approval["native_runner"][limit] = value
    storage.write(b.path, b.approval, replace=True)
    b.access._guest = MagicMock(side_effect=TimeoutError("private"))
    assert b.actions.call(b.principal, "native_runner_submit", b.args)["status"] == "UNKNOWN"
    restored = NativeRunnerActions(b.access, b.inputs, b.paths, guest_ready=True)
    with pytest.raises(InvalidArtifact, match="budget_exhausted"):
        restored.call(b.principal, "native_runner_submit", {**b.args, "idempotency_key": "second"})
    b.access._guest.assert_called_once()


def test_status_reconciles_unknown_only_with_matching_native_pins(bridge):
    b = bridge
    guest = b.access._guest

    def ambiguous(operation, args):
        guest(operation, args)
        raise TimeoutError("lost acknowledgement")

    b.access._guest = ambiguous
    result = b.actions.call(b.principal, "native_runner_submit", b.args)
    assert result["status"] == "UNKNOWN"
    jid = result["job_id"]
    runner_guest.run_job(jid, transport=SyntheticTransport(truncate_control=False))
    b.access._guest = guest
    assert (
        b.actions.call(b.principal, "native_runner_status", {"job_id": jid})["status"]
        == "COMPLETED"
    )
    b.access._guest = lambda op, args: {**guest(op, args), "plan_sha256": "0" * 64}
    with pytest.raises(InvalidArtifact, match="native_job_pin_mismatch"):
        b.actions.call(b.principal, "native_runner_status", {"job_id": jid})


def test_approval_refresh_revocation_blocks_before_dispatch(bridge):
    b = bridge

    def revoke():
        storage.write(b.path, {**b.approval, "approved": False}, replace=True)

    b.actions.refresh_approval = revoke
    with pytest.raises(InvalidArtifact):
        b.actions.call(b.principal, "native_runner_submit", b.args)
    assert not b.requests and not b.launches


def test_budget_and_busy_limits_and_source_tampering_fail_closed(bridge):
    b = bridge
    b.actions.call(b.principal, "native_runner_submit", b.args)
    with pytest.raises(InvalidArtifact, match="already_busy"):
        b.actions.call(b.principal, "native_runner_submit", {**b.args, "idempotency_key": "second"})
    p = b.inputs.paths[0]
    p.write_bytes(p.read_bytes() + b" ")
    with pytest.raises(InvalidArtifact, match="native_runner_source_changed"):
        b.actions.call(b.principal, "native_runner_catalog", {})


def test_guest_rejects_tampered_plan_and_never_launches_real_calls_for_synthetic_model(bridge):
    b = bridge
    first = b.actions.call(b.principal, "native_runner_submit", b.args)
    req = dict(b.requests[0][1])
    req["plan_sha256"] = "0" * 64
    with pytest.raises(InvalidArtifact, match="native_plan_mismatch"):
        runner_guest.handle("native_submit", req, launch=MagicMock())
    result = runner_guest.run_job(first["job_id"])
    assert result["status"] == "UNKNOWN" and result["attempts"] == 0
    root = b.work / ".native-runner" / first["job_id"]
    assert not (root / "runs").exists()
    assert runner_guest.run_job(first["job_id"]) == result


def test_guest_export_tampering_and_paths_are_rejected(bridge):
    b = bridge
    first = b.actions.call(b.principal, "native_runner_submit", b.args)
    jid = first["job_id"]
    runner_guest.run_job(jid, transport=SyntheticTransport(truncate_control=False))
    p = b.work / ".native-runner" / jid / "export.json"
    p.write_bytes(p.read_bytes() + b" ")
    with pytest.raises(InvalidArtifact, match="native_export_integrity"):
        b.actions.call(b.principal, "native_runner_result", {"job_id": jid, "offset": 0})
    for value in ("../escape", "/etc/passwd"):
        with pytest.raises(InvalidArtifact):
            runner_guest.handle("native_status", {"job_id": value})


def test_native_guest_attests_actual_fixed_runtime_files_before_real_inference(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runner_guest, "MODEL_ROOT", tmp_path)
    model, runtime = tmp_path / "Qwen3-1.7B-Q4_K_M.gguf", tmp_path / "llama-server"
    model.write_bytes(b"synthetic-model")
    runtime.write_bytes(b"synthetic-runtime")
    manifest = {"model_sha256": sha256_file(model), "runtime_sha256": sha256_file(runtime)}
    runner_guest.attest_files(manifest)
    runtime.write_bytes(b"modified")
    with pytest.raises(InvalidArtifact, match="native_runtime_file_mismatch"):
        runner_guest.attest_files(manifest)
    runtime.unlink()
    runtime.symlink_to(model)
    with pytest.raises(InvalidArtifact, match="native_runtime_file_not_unique"):
        runner_guest.attest_files(manifest)


def test_guest_deadline_and_started_intent_prevent_relaunch(bridge):
    b = bridge
    first = b.actions.call(b.principal, "native_runner_submit", b.args)
    req = dict(b.requests[0][1])
    req["deadline"] = 1
    launch = MagicMock()
    with pytest.raises(InvalidArtifact, match="native_job_deadline_invalid"):
        runner_guest.handle("native_submit", req, launch=launch)
    launch.assert_not_called()
    root = b.work / ".native-runner" / first["job_id"]
    storage.write(root / "started.json", {"at": time.time()})
    transport = MagicMock()
    assert runner_guest.run_job(first["job_id"], transport=transport)["status"] == "UNKNOWN"
    transport.assert_not_called()


def test_real_mcp_transport_enforces_runner_scopes_and_narrow_actions(bridge, oauth):
    config, _, fetch, token, _ = oauth
    b = bridge
    app = create_app(config, fetch=fetch, native_actions=b.actions)
    with TestClient(app, base_url="https://mcp.example.test") as client:
        assert rpc(client, "tools/list").status_code == 401
        tools = rpc(client, "tools/list", bearer=token(scope=READ_SCOPE)).json()["result"]["tools"]
        assert {t["name"] for t in tools} == set(TOOLS)
        assert not any(t["name"] in {"vm_exec", "vm_write", "vm_read"} for t in tools)
        meta = client.get("/.well-known/oauth-protected-resource/mcp").json()
        assert meta["scopes_supported"] == [READ_SCOPE, EXECUTE_SCOPE]
        denied = rpc(
            client,
            "tools/call",
            {"name": "native_runner_submit", "arguments": b.args},
            token(scope=READ_SCOPE),
        ).json()["result"]
        assert denied["isError"] and not b.requests
        result = rpc(
            client,
            "tools/call",
            {"name": "native_runner_submit", "arguments": b.args},
            token(scope=READ_SCOPE + " " + EXECUTE_SCOPE),
        ).json()["result"]
        assert result["structuredContent"]["status"] == "RUNNING"


def test_native_backend_has_no_tunnel_dependency_or_generic_guest_access(bridge):
    b = bridge
    secrets = MagicMock()
    secrets.read.side_effect = lambda name: {
        "authorization": b.path.read_bytes(),
        "ssh": b"synthetic",
    }[name]
    backend = NativeBackendAccess(b.access.config, secrets)
    backend.cloud.inspect = lambda: {"status": "TERMINATED"}
    backend.call("vm_status", {})
    assert [c.args[0] for c in secrets.read.call_args_list] == ["authorization", "ssh"]
    with pytest.raises(InvalidArtifact, match="native_lifecycle_only"):
        backend.call("vm_exec", {"command": "id"})
    with pytest.raises(InvalidArtifact, match="native_guest_operation_required"):
        backend._guest("exec", {"command": "id"})
    with pytest.raises(InvalidArtifact, match="native_approval_changed_before_dispatch"):
        backend._guest("native_submit", {"approval_sha256": "0" * 64})


def test_native_bundle_reuses_runner_and_excludes_campaign_algorithm(tmp_path):
    path = Path(__file__).parents[1] / "backend/build_bundle.py"
    spec = importlib.util.spec_from_file_location("native_bundle", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import tarfile

    output = tmp_path / "bundle.tgz"
    module.build(output, native_runner=True)
    with tarfile.open(output) as tar:
        files = json.load(tar.extractfile("manifest.json"))["files"]
        assert "jewelai_research/native_jobs.py" in files
        assert "native_llm_bench/runner.py" in files
        assert files["native_llm_bench/runner.py"] == sha256_file(
            FIXTURES.parent / "src/native_llm_bench/runner.py"
        )
        assert not any(x in p for p in files for x in ("controller", "worker", "synthetic"))
