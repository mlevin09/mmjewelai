import io
import json

import pytest
from native_llm_bench.contracts import InvalidArtifact, digest

from jewelai_research import vm_guest
from jewelai_research.vm_access import VmAccess, serve


@pytest.fixture
def access(tmp_path):
    authorization = tmp_path / "authorization.json"
    authorization.write_text('{"approved":false}')
    return VmAccess(
        {
            "gcloud": "FAKE",
            "state": str(tmp_path / "state"),
            "authorization": str(authorization),
            "ssh_key": "private-key-path",
            "known_hosts": "verified-hosts-path",
            "guest_ready": False,
        }
    )


def test_status_works_with_stopped_vm_and_no_campaign(access):
    access.cloud.inspect = lambda: {
        "status": "TERMINATED",
        "scheduling": {"maxRunDuration": {"seconds": "1200"}},
    }
    assert access.call("vm_status", {})["status"] == "TERMINATED"
    assert access.lease.read() is None


def test_start_requires_owner_approval_before_any_paid_call(access):
    access.cloud.inspect = lambda: pytest.fail("must not call cloud")
    with pytest.raises(InvalidArtifact, match="owner_start_authorization_required"):
        access.call("vm_start", {})


@pytest.mark.parametrize("args", [{"command": "gcloud projects delete anything"}, {"vm": "other"}])
def test_local_cloud_administration_cannot_be_injected(access, args):
    with pytest.raises(InvalidArtifact):
        access.call("vm_start", args)


def test_unowned_remote_execution_is_denied(access):
    access.config["guest_ready"] = True
    with pytest.raises(InvalidArtifact, match="owned_vm_required"):
        access.call("vm_exec", {"command": "id"})


def test_stdio_discovers_infrastructure_tools_only_and_reads_actual_handler(access):
    access.cloud.inspect = lambda: {"status": "TERMINATED"}
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "vm_status", "arguments": {}},
        },
    ]
    output = io.StringIO()
    serve(access, io.StringIO("\n".join(json.dumps(m) for m in messages)), output)
    results = [json.loads(s)["result"] for s in output.getvalue().splitlines()]
    assert {t["name"] for t in results[0]["tools"]} == {
        "vm_status",
        "vm_start",
        "vm_exec",
        "vm_job",
        "vm_read",
        "vm_write",
        "vm_stop",
    }
    assert results[1]["structuredContent"]["status"] == "TERMINATED"


def test_guest_files_are_scoped_and_source_is_read_only(tmp_path, monkeypatch):
    work, source = tmp_path / "work", tmp_path / "source"
    work.mkdir()
    source.mkdir()
    monkeypatch.setattr(vm_guest, "WORK", work)
    monkeypatch.setattr(vm_guest, "SOURCE", source)
    vm_guest.handle("write", {"path": "procedure.py", "content": "print('research')"})
    assert vm_guest.handle("read", {"path": "procedure.py"})["content"] == "print('research')"
    for path in ["../outside", "/etc/passwd", "source/canonical.py"]:
        with pytest.raises(ValueError):
            vm_guest.handle("write", {"path": path, "content": "cannot modify"})
    (work / "escape").symlink_to(tmp_path)
    with pytest.raises(ValueError):
        vm_guest.handle("read", {"path": "escape/authorization.json"})


def test_lease_tampering_fails_closed(access):
    from native_llm_bench.storage import write

    write(access.root / "lease.json", {"lease": {"phase": "OWNED"}, "sha256": digest({})})
    with pytest.raises(InvalidArtifact, match="lease_integrity"):
        access.lease.read()


def test_strict_host_key_path_with_spaces_stays_one_path(access, monkeypatch):
    import shlex
    from types import SimpleNamespace

    from jewelai_research import vm_access

    access.config.update(guest_ready=True, known_hosts="/private/verified hosts/known_hosts")
    identity = {"instance_id": "123", "last_start": "2026-11-12T00:00:00Z"}
    access.lease.read = lambda: {"phase": "OWNED", "fingerprint": identity}
    access.lease.cancelled = lambda: False
    access.cloud.inspect = lambda: {
        "status": "RUNNING",
        "id": "123",
        "lastStartTimestamp": identity["last_start"],
    }

    def run(args, **kwargs):
        option = next(s for s in args if s.startswith("UserKnownHostsFile="))
        assert shlex.split(option.split("=", 1)[1]) == [access.config["known_hosts"]]
        assert kwargs["env"]["SHELL"] == "/bin/sh"
        assert "StrictHostKeyChecking=yes" in args
        assert args[-1] == "jewelai-research@jewelai-llm-lab"
        return SimpleNamespace(returncode=0, stdout=b'{"content":"ok"}')

    monkeypatch.setattr(vm_access.subprocess, "run", run)
    assert access.call("vm_read", {"path": "result.txt"}) == {"content": "ok"}


def owned(access, phase="OWNED", **facts):
    identity = {"instance_id": "123", "last_start": "2026-11-12T00:00:00Z"}
    access.lease._save({"lease_id": "test", "phase": phase, "fingerprint": identity, **facts})
    return {"id": "123", "lastStartTimestamp": identity["last_start"]}


def test_slow_stop_is_submitted_once_and_reconciled_without_new_rpc(access):
    instance = owned(access)
    access.cloud.inspect = lambda: {**instance, "status": "RUNNING"}
    calls = []

    def stop():
        assert access.cloud.fenced
        calls.append("stop")
        return {"name": "owned-stop"}

    access.cloud.request_stop = stop
    access.cloud.operation = lambda name: {"status": "RUNNING"}
    assert access.call("vm_stop", {}) == {"status": "STOPPING", "verified_stopped": False}
    assert not access.cloud.fenced
    assert access.call("vm_stop", {})["status"] == "STOPPING"
    access.cloud.inspect = lambda: {**instance, "status": "STOPPING"}
    assert access.call("vm_stop", {})["status"] == "STOPPING"
    access.cloud.inspect = lambda: {**instance, "status": "TERMINATED"}
    assert access.call("vm_status", {})["lease"]["phase"] == "RELEASED"
    assert access.call("vm_stop", {})["verified_stopped"]
    assert calls == ["stop"]


def test_stop_cannot_adopt_another_incarnation(access):
    instance = owned(access)
    access.cloud.inspect = lambda: {**instance, "status": "RUNNING", "id": "999"}
    access.cloud.request_stop = lambda: pytest.fail("must not stop unowned VM")
    with pytest.raises(InvalidArtifact, match="vm_ownership_changed"):
        access.call("vm_stop", {})


@pytest.mark.parametrize("same", [True, False])
def test_prior_stop_timeout_reconciles_only_the_owned_stopped_incarnation(access, same):
    instance = owned(access, "BLOCKED", reason="owned_shutdown_not_verified")
    access.cloud.inspect = lambda: {
        **instance,
        "status": "TERMINATED",
        "id": "123" if same else "999",
    }
    access.cloud.request_stop = lambda: pytest.fail("readback must not mutate cloud")
    phase = access.call("vm_status", {})["lease"]["phase"]
    assert phase == ("RELEASED" if same else "BLOCKED")


def test_status_recovers_recorded_start_without_duplicate_start(access):
    import time
    from pathlib import Path

    from jewelai_research.contracts import TARGET
    from jewelai_research.lifecycle import SyntheticLab

    Path(access.config["authorization"]).write_text(
        json.dumps(
            {
                "approved": True,
                "target": TARGET,
                "expires_at": int(time.time()) + 60,
                "maximum_starts": 1,
            }
        )
    )
    lab = SyntheticLab()
    access.cloud = lab
    lease = access.lease.begin({})
    operation = lab.request_start()
    access.lease.record(
        lease["lease_id"], "START_SUBMITTED", instance_id="123", operation_name=operation["name"]
    )
    assert access.call("vm_status", {})["lease"]["phase"] == "OWNED"
    assert access.call("vm_status", {})["lease"]["phase"] == "OWNED"
    assert lab.starts == 1 and lab.stops == 0


def test_completion_authorization_has_no_time_or_start_count_cutoff(access):
    from native_llm_bench.storage import write

    from jewelai_research.contracts import TARGET

    write(
        access.config["authorization"],
        {
            "approved": True,
            "target": TARGET,
            "shutdown_policy": "completion",
            "operation_id": "R1",
            "native_runner": True,
        },
        replace=True,
    )
    access.lease.begin({})
    access.lease.record(access.lease.read()["lease_id"], "RELEASED")
    access.lease.begin({})
    assert not access.lease.cancelled()
    access.config["guest_ready"] = True
    access.cloud.inspect = lambda: {"scheduling": {"maxRunDuration": {"seconds": "420"}}}
    with pytest.raises(InvalidArtifact, match="premature_shutdown"):
        access.call("vm_start", {})


def test_failed_stop_request_can_recover_only_same_owned_incarnation(access):
    instance = owned(access)
    access.cloud.inspect = lambda: {**instance, "status": "RUNNING"}
    access.cloud.request_stop = lambda: (_ for _ in ()).throw(OSError("unavailable"))
    with pytest.raises(OSError):
        access.call("vm_stop", {})
    assert access.lease.read()["phase"] == "STOP_INTENT"
    access.cloud.request_stop = lambda: {"name": "recovered"}
    assert access.call("vm_stop", {})["status"] == "STOPPING"
    assert access.lease.read()["stop_operation"] == "recovered"


def test_finish_stop_intent_cannot_race_into_new_lease(access):
    instance = owned(access)
    access.cloud.inspect = lambda: {**instance, "status": "RUNNING"}
    access.cloud.request_stop = lambda: pytest.fail("must not stop replacement lease")
    with pytest.raises(InvalidArtifact, match="finish_lease_changed"):
        access.call("vm_stop", {}, expected_lease="previous-campaign")
