"""Fixed existing-VM lifecycle only. No shell, IAM writes, new VM, public ports or resizing."""

import subprocess
import time
from pathlib import Path

from native_llm_bench.contracts import decode, require

from .contracts import MODEL_SHA, RUNTIME_SHA, TARGET
from .owned_lifecycle import OwnedLifecycle

# Static command, never assembled from agent text. Hash actual files on each future start.
ATTEST = """python3 - <<'PY'
import hashlib, json
from pathlib import Path
root = Path('/opt/jewelai-llm-lab')
result = {}
for key, name in [('model_sha256', 'Qwen3-1.7B-Q4_K_M.gguf'),
                  ('runtime_sha256', 'llama-server')]:
    paths = [p for p in root.rglob(name) if p.is_file() and not p.is_symlink()]
    assert len(paths) == 1
    h = hashlib.sha256()
    with paths[0].open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    result[key] = h.hexdigest()
print(json.dumps(result))
PY"""


class SyntheticLab(OwnedLifecycle):
    """Explicit fake cloud; uses the SAME lease/operation ownership algorithm as GCP."""

    def __init__(self):
        self.current, self.starts, self.stops = "TERMINATED", 0, 0
        self.last_start = "2026-01-01T00:00:00Z"
        self.sleep = lambda _: None

    def check_envelope(self, envelope):
        require(envelope["mode"] == "SYNTHETIC", "synthetic_only")

    def check_instance(self, instance):
        pass

    def inspect(self):
        return {"id": "123", "status": self.current, "lastStartTimestamp": self.last_start}

    def request_start(self):
        self.starts += 1
        self.current = "RUNNING"
        self.last_start = f"2026-01-01T00:{self.starts:02}:01Z"
        return {"name": "synthetic-operation-" + str(self.starts)}

    def operation(self, name):
        return {
            "name": name,
            "operationType": "start",
            "targetId": "123",
            "status": "DONE",
            "targetLink": "https://compute.invalid/projects/{project}/zones/{zone}/instances/{vm}".format(
                **TARGET
            ),
            "startTime": f"2026-01-01T00:{self.starts:02}:00Z",
            "endTime": f"2026-01-01T00:{self.starts:02}:02Z",
        }

    def request_stop(self):
        self.stops += 1
        self.current = "TERMINATED"


class GcpLab(OwnedLifecycle):
    """Fixed existing VM only. Current CLI cannot issue a live activation permit."""

    def __init__(
        self,
        gcloud,
        *,
        activation_permit=False,
        run=subprocess.run,
        sleep=time.sleep,
        tunnel=None,
        exclusive_use=None,
    ):
        self.gcloud, self.permit, self.run, self.sleep = gcloud, activation_permit, run, sleep
        self.tunnel = tunnel
        self.exclusive_use = exclusive_use
        self.fenced = False

    def start(self, envelope, journal):
        self.check_envelope(envelope)
        require(self.exclusive_use is not None, "exclusive_vm_use_not_qualified")
        with self.exclusive_use():
            self.fenced = True
            try:
                return super().start(envelope, journal)
            finally:
                self.fenced = False

    def stop(self, journal=None):
        from .leases import LeaseJournal

        require(isinstance(journal, LeaseJournal), "durable_lease_required")
        lease = journal.read()
        if not lease or lease["phase"] not in {"START_SUBMITTED", "OWNED", "STOP_INTENT"}:
            return super().stop(journal)
        if self.exclusive_use is None:
            return journal.blocked("exclusive_vm_use_not_qualified")
        with self.exclusive_use():
            self.fenced = True
            try:
                return super().stop(journal)
            finally:
                self.fenced = False

    def _command(self, operation, operation_name=None):
        require(self.permit, "live_activation_not_authorized")
        require(operation in ("describe", "start", "stop", "operation"), "forbidden_gcp_operation")
        if operation in {"start", "stop"}:
            require(self.fenced, "exclusive_vm_use_not_qualified")
        if operation == "operation":
            import re

            require(
                isinstance(operation_name, str)
                and re.fullmatch(r"[a-zA-Z0-9_-]{1,200}", operation_name),
                "invalid_operation_identity",
            )
            args = [self.gcloud, "compute", "operations", "describe", operation_name]
        else:
            args = [self.gcloud, "compute", "instances", operation, TARGET["vm"]]
        args += [
            "--project=" + TARGET["project"],
            "--zone=" + TARGET["zone"],
            "--format=json",
            "--quiet",
        ]
        if operation in ("start", "stop"):
            args.append("--async")
        result = self.run(args, capture_output=True, timeout=120, check=False)
        require(result.returncode == 0, "gcp_lifecycle_failed")
        data = decode(result.stdout)
        if isinstance(data, list):
            require(len(data) == 1, "unexpected_operation_count")
            data = data[0]
        return data

    def check_envelope(self, envelope):
        require(envelope["mode"] == "LIVE" and envelope["target"] == TARGET, "wrong_live_target")

    def check_instance(self, d):
        require(
            d["name"] == TARGET["vm"]
            and d["machineType"].endswith("/e2-medium")
            and not d.get("serviceAccounts")
            and not d.get("guestAccelerators")
            and all(
                not n.get("accessConfigs") and not n.get("ipv6AccessConfigs")
                for n in d["networkInterfaces"]
            ),
            "vm_configuration_mismatch",
        )

    def inspect(self):
        return self._command("describe")

    def request_start(self):
        return self._command("start")

    def operation(self, name):
        return self._command("operation", name)

    def request_stop(self):
        return self._command("stop")

    def open(self):
        require(self.tunnel is not None, "private_tunnel_not_configured")
        self.tunnel.open()

    def close(self):
        if self.tunnel is not None:
            self.tunnel.close()


class PrivateTunnel:
    """Existing IAP SSH authorization/key only. No gcloud compute ssh metadata/key writes.

    Operator supplies an existing private key and preverified known_hosts file. No agent-
    selected path/command; StrictHostKeyChecking=yes. The fixed remote attestation precedes
    loopback forwarding. Hosting composition is deliberately not enabled by current CLI.
    """

    def __init__(
        self,
        gcloud,
        ssh_key,
        known_hosts,
        *,
        activation_permit=False,
        run=subprocess.run,
        popen=subprocess.Popen,
    ):
        self.gcloud, self.key, self.hosts = gcloud, Path(ssh_key), Path(known_hosts)
        self.permit, self.run, self.popen = activation_permit, run, popen
        self.process = None

    def _ssh(self):
        require(self.permit, "live_activation_not_authorized")
        require(self.key.is_file() and self.hosts.is_file(), "authorized_ssh_material_missing")
        # ProxyCommand is local OpenSSH syntax. Every word is an operator-pinned executable
        # or a constant; none can originate in tool/corpus/model output.
        import shlex

        proxy = shlex.join(
            [
                self.gcloud,
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
        return [
            "ssh",
            "-T",
            "-i",
            str(self.key),
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "UserKnownHostsFile=" + str(self.hosts),
            "-o",
            "HostKeyAlias=jewelai-llm-lab",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "ProxyCommand=" + proxy,
            "llmlab@" + TARGET["vm"],
        ]

    def open(self):
        require(self.process is None, "tunnel_already_open")
        result = self.run([*self._ssh(), ATTEST], capture_output=True, timeout=90, check=False)
        require(result.returncode == 0, "runtime_attestation_failed")
        require(
            decode(result.stdout) == {"model_sha256": MODEL_SHA, "runtime_sha256": RUNTIME_SHA},
            "runtime_attestation_mismatch",
        )
        ssh = self._ssh()
        self.process = self.popen(
            [
                *ssh[:-1],
                "-o",
                "ExitOnForwardFailure=yes",
                "-o",
                "ServerAliveInterval=10",
                "-o",
                "ServerAliveCountMax=2",
                "-N",
                "-L",
                "127.0.0.1:8080:127.0.0.1:8080",
                ssh[-1],
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Readiness/health is checked by the caller before inference. An occupied local
        # port makes SSH exit; never reuse a listener from an unknown process.
        import http.client

        for _ in range(20):
            require(self.process.poll() is None, "private_tunnel_failed")
            time.sleep(0.1)
            connection = http.client.HTTPConnection("127.0.0.1", 8080, timeout=1)
            try:
                connection.request("GET", "/health")
                response = connection.getresponse()
                if response.status == 200:
                    require(self.process.poll() is None, "private_tunnel_failed")
                    return
            except OSError:
                pass
            finally:
                connection.close()
        require(False, "model_readiness_not_verified")

    def close(self):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
            self.process = None
