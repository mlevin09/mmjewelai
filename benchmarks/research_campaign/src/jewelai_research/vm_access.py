"""Private stdio VM access. Infrastructure only; no campaigns, profiles or scientific policy."""

import argparse
import contextlib
import fcntl
import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path

from native_llm_bench.contracts import canonical, digest, keys, load, require
from native_llm_bench.storage import write

from .contracts import TARGET
from .leases import LeaseJournal
from .lifecycle import GcpLab
from .owned_lifecycle import fingerprint

TOOLS = {
    "vm_status": {},
    "vm_start": {},
    "vm_stop": {},
    "vm_exec": {"command": {"type": "string", "maxLength": 32768}},
    "vm_job": {"job_id": {"type": "string", "maxLength": 32}},
    "vm_read": {"path": {"type": "string", "maxLength": 1024}},
    "vm_write": {
        "path": {"type": "string", "maxLength": 1024},
        "content": {"type": "string", "maxLength": 65536},
    },
}


class AccessLease(LeaseJournal):
    """Reuse only the lifecycle journal interface; no Controller or experiment runtime."""

    def __init__(self, root, authorization):
        self.root, self.authorization = Path(root), Path(authorization)

    def read(self):
        p = self.root / "lease.json"
        if not p.exists():
            return None
        r = load(p)
        require(digest(r["lease"]) == r["sha256"], "lease_integrity")
        return r["lease"]

    def _save(self, lease):
        write(self.root / "audit" / (uuid.uuid4().hex + ".json"), lease)
        write(self.root / "lease.json", {"lease": lease, "sha256": digest(lease)}, replace=True)
        return lease

    def authorized(self):
        a = load(self.authorization)
        require(
            a.get("target") == TARGET
            and a.get("approved") is True
            and (
                (
                    a.get("shutdown_policy") == "completion"
                    and isinstance(a.get("operation_id"), str)
                    and 1 <= len(a["operation_id"]) <= 80
                    and a.get("native_runner") is True
                )
                or (
                    "shutdown_policy" not in a
                    and type(a.get("expires_at")) is int
                    and time.time() < a["expires_at"]
                    and type(a.get("maximum_starts")) is int
                    and a["maximum_starts"] > 0
                )
            ),
            "owner_start_authorization_required",
        )
        return a

    def begin(self, envelope):
        a = self.authorized()
        old = self.read()
        require(old is None or old["phase"] in {"RELEASED", "NO_START"}, "ownership_blocked")
        starts = sum(
            load(x)["authorization_sha256"] == digest(a) for x in self.root.glob("*.start")
        )
        require(
            a.get("shutdown_policy") == "completion" or starts < a["maximum_starts"],
            "authorized_start_count_exhausted",
        )
        token = uuid.uuid4().hex
        write(
            self.root / (token + ".start"), {"at": time.time(), "authorization_sha256": digest(a)}
        )
        return self._save(
            {
                "lease_id": token,
                "phase": "CHECKING",
                "at": time.time(),
                "operation_id": a.get("operation_id"),
            }
        )

    def record(self, lease_id, phase, **facts):
        old = self.read()
        require(old and old["lease_id"] == lease_id, "lease_identity_mismatch")
        return self._save({**old, **facts, "phase": phase, "at": time.time()})

    def cancelled(self):
        try:
            self.authorized()
            return False
        except ValueError:
            return True


class VmAccess:
    def __init__(self, config):
        keys(config, ("gcloud", "state", "authorization", "ssh_key", "known_hosts", "guest_ready"))
        self.config = config
        self.root = Path(config["state"])
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        require(self.root.stat().st_mode & 0o077 == 0, "private_state_required")
        self.lease = AccessLease(self.root, config["authorization"])
        self.cloud = GcpLab(config["gcloud"], activation_permit=True, exclusive_use=self.locked)
        # No model tunnel or experiment layer. SSH is opened per scoped guest operation.
        self.cloud.open = lambda: None

    @contextlib.contextmanager
    def locked(self):
        fd = os.open(self.root / "vm.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def _guest(self, operation, arguments):
        require(self.config["guest_ready"] is True, "non_root_guest_not_installed")
        lease = self.lease.read()
        require(lease and lease["phase"] == "OWNED", "owned_vm_required")
        d = self.cloud.inspect()
        require(
            d["status"] == "RUNNING" and fingerprint(d) == lease["fingerprint"], "owned_vm_required"
        )
        require(not self.lease.cancelled(), "owner_start_authorization_required")
        proxy = shlex.join(
            [
                self.config["gcloud"],
                "compute",
                "start-iap-tunnel",
                TARGET["vm"],
                "22",
                "--listen-on-stdin",
                "--project=" + TARGET["project"],
                "--zone=" + TARGET["zone"],
                "--verbosity=error",
            ]
        )
        args = [
            "ssh",
            "-T",
            "-i",
            self.config["ssh_key"],
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "UserKnownHostsFile=" + shlex.quote(self.config["known_hosts"]),
            "-o",
            "HostKeyAlias=jewelai-llm-lab",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "ProxyCommand=" + proxy,
            "jewelai-research@" + TARGET["vm"],
        ]
        r = subprocess.run(
            args,
            input=canonical({"operation": operation, "arguments": arguments}),
            # ssh executes ProxyCommand with SHELL. The service account keeps its
            # nologin login shell; only this fixed IAP subprocess needs /bin/sh.
            env={**os.environ, "SHELL": "/bin/sh"},
            capture_output=True,
            timeout=35,
            check=False,
        )
        require(r.returncode == 0 and len(r.stdout) <= 200000, "guest_request_failed")
        return json.loads(r.stdout)

    def call(self, name, arguments, *, expected_lease=None):
        require(name in TOOLS, "unknown_tool")
        keys(arguments, TOOLS[name])
        if name == "vm_status":
            with self.locked():
                d = self.cloud.inspect()
                lease = self.lease.read()
                if lease and lease["phase"] == "START_SUBMITTED":
                    # Read-only recovery of a recorded successful start, never a new RPC.
                    self.cloud.adopt(self.lease)
                    d, lease = self.cloud.inspect(), self.lease.read()
                # A slow asynchronous stop is not a new VM lease or a failed shutdown.
                # Reconcile only an already proven incarnation, without a cloud write.
                if (
                    lease
                    and (
                        lease["phase"] == "STOP_INTENT"
                        or (
                            lease["phase"] == "BLOCKED"
                            and lease.get("reason") == "owned_shutdown_not_verified"
                        )
                    )
                    and d["status"] == "TERMINATED"
                    and fingerprint(d) == lease.get("fingerprint")
                ):
                    self.lease.record(lease["lease_id"], "RELEASED")
            return {
                "target": TARGET,
                "status": d["status"],
                "lease": self.lease.read(),
                "maximum_runtime_seconds": d.get("scheduling", {})
                .get("maxRunDuration", {})
                .get("seconds"),
                "guest_ready": self.config["guest_ready"],
            }
        if name == "vm_start":
            approval = self.lease.authorized()  # Protected host-only policy.
            require(self.config["guest_ready"] is True, "non_root_guest_not_installed")
            d = self.cloud.inspect()
            scheduling = d.get("scheduling", {})
            if approval.get("shutdown_policy") == "completion":
                require(
                    not scheduling.get("maxRunDuration") and not scheduling.get("terminationTime"),
                    "premature_shutdown_still_configured",
                )
            else:
                require(
                    scheduling.get("instanceTerminationAction") == "STOP"
                    and 0 < int(scheduling.get("maxRunDuration", {}).get("seconds", 0)) <= 1200,
                    "automatic_shutdown_not_verified",
                )
            with self.locked():
                lease = self.lease.read()
                if d["status"] == "RUNNING" and lease and lease["phase"] == "OWNED":
                    require(
                        fingerprint(d) == lease["fingerprint"]
                        and lease.get("operation_id") == approval.get("operation_id"),
                        "vm_ownership_changed",
                    )
                    return {"status": "RUNNING", "lease": lease}
            self.cloud.start({"mode": "LIVE", "target": TARGET}, self.lease)
            return {"status": "RUNNING", "lease": self.lease.read()}
        if name == "vm_stop":
            # Cloud stop is asynchronous. Return promptly and let vm_status verify its
            # completion; never submit a second RPC because shutdown exceeds one minute.
            with self.locked():
                lease = self.lease.read()
                require(
                    expected_lease is None or (lease and lease["lease_id"] == expected_lease),
                    "finish_lease_changed",
                )
                require(
                    lease and lease["phase"] in {"OWNED", "STOP_INTENT", "RELEASED"},
                    "ownership_not_proven",
                )
                if lease["phase"] == "RELEASED":
                    return {"verified_stopped": True, "status": "RELEASED"}
                d = self.cloud.inspect()
                require(fingerprint(d) == lease.get("fingerprint"), "vm_ownership_changed")
                if d["status"] == "TERMINATED":
                    self.lease.record(lease["lease_id"], "RELEASED")
                    return {"verified_stopped": True, "status": "RELEASED"}
                require(d["status"] in {"RUNNING", "STOPPING"}, "owned_vm_not_stoppable")
                retry_stop = lease["phase"] == "STOP_INTENT" and not lease.get("stop_operation")
                if lease.get("stop_operation") and d["status"] == "RUNNING":
                    op = self.cloud.operation(lease["stop_operation"])
                    retry_stop = op.get("status") == "DONE" and bool(op.get("error"))
                if (lease["phase"] == "OWNED" or retry_stop) and d["status"] == "RUNNING":
                    self.lease.record(lease["lease_id"], "STOP_INTENT")
                    self.cloud.fenced = True
                    try:
                        operation = self.cloud.request_stop()
                    finally:
                        self.cloud.fenced = False
                    self.lease.record(
                        lease["lease_id"], "STOP_INTENT", stop_operation=operation.get("name")
                    )
                return {"verified_stopped": False, "status": "STOPPING"}
        with self.locked():
            return self._guest(name.removeprefix("vm_"), arguments)


def serve(access, source=sys.stdin, sink=sys.stdout):
    """Private stdio only: authenticated tunnel owns invocation. Never bind a public listener."""
    for line in source:
        request = None
        try:
            require(len(line.encode()) <= 100000, "request_too_large")
            request = json.loads(line)
            method = request["method"]
            if method.startswith("notifications/"):
                continue
            require(
                request.get("jsonrpc") == "2.0" and type(request.get("id")) in (int, str),
                "invalid_rpc",
            )
            if method == "initialize":
                result = {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "jewelai-vm-access", "version": "1.0.0"},
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": n,
                            "description": "Use the existing CPU research VM: " + n,
                            "inputSchema": {
                                "type": "object",
                                "properties": p,
                                "required": list(p),
                                "additionalProperties": False,
                            },
                        }
                        for n, p in TOOLS.items()
                    ]
                }
            else:
                require(method == "tools/call", "unknown_method")
                p = request["params"]
                value = access.call(p["name"], p["arguments"])
                result = {
                    "content": [{"type": "text", "text": canonical(value).decode()}],
                    "structuredContent": value,
                    "isError": False,
                }
            response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except Exception:
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id") if isinstance(request, dict) else None,
                "error": {"code": -32602, "message": "vm_access_blocked"},
            }
        sink.write(canonical(response).decode() + "\n")
        sink.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    path = Path(args.config)
    require(path.stat().st_mode & 0o077 == 0, "private_config_required")
    serve(VmAccess(load(path)))


if __name__ == "__main__":
    main()
