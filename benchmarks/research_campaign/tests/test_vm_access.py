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
