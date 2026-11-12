"""Fixed existing-VM lifecycle only. No shell, IAM writes, new VM, public ports or resizing."""

import subprocess
import time
from pathlib import Path

from native_llm_bench.contracts import decode, require

from .contracts import MODEL_SHA, RUNTIME_SHA, TARGET

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


class SyntheticLab:
    """Explicit test double, never evidence of cloud or model execution."""

    def __init__(self):
        self.current = "TERMINATED"
        self.starts = 0
        self.stops = 0

    def start(self, envelope):
        require(envelope["mode"] == "SYNTHETIC", "synthetic_only")
        self.starts += 1
        self.current = "RUNNING"

    def stop(self):
        self.stops += 1
        self.current = "TERMINATED"

    def status(self):
        return self.current


class GcpLab:
    """Deployment candidate, NOT activated. No credentials or target accepted from tool args.

    Existing operator gcloud/IAP access only. Explicit permit supplied by future reviewed
    hosting/activation composition; current CLI has NO live activation path. Proxy metering
    cannot issue that permit. Commands are argv lists, and errors discard stdout/stderr.
    """

    def __init__(
        self, gcloud, *, activation_permit=False, run=subprocess.run, sleep=time.sleep, tunnel=None
    ):
        self.gcloud, self.permit, self.run, self.sleep = gcloud, activation_permit, run, sleep
        self.tunnel = tunnel

    def _command(self, operation):
        require(self.permit, "live_activation_not_authorized")
        require(operation in ("describe", "start", "stop"), "forbidden_gcp_operation")
        args = [
            self.gcloud,
            "compute",
            "instances",
            operation,
            TARGET["vm"],
            "--project=" + TARGET["project"],
            "--zone=" + TARGET["zone"],
            "--format=json",
            "--quiet",
        ]
        result = self.run(args, capture_output=True, timeout=120, check=False)
        require(result.returncode == 0, "gcp_lifecycle_failed")
        return decode(result.stdout)

    def status(self):
        return self._command("describe")["status"]

    def start(self, envelope):
        require(envelope["mode"] == "LIVE" and envelope["target"] == TARGET, "wrong_live_target")
        d = self._command("describe")
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
        require(d["status"] == "TERMINATED", "vm_not_exclusively_stopped")
        self._command("start")
        for _ in range(12):
            if self.status() == "RUNNING":
                require(self.tunnel is not None, "private_tunnel_not_configured")
                self.tunnel.open()
                return
            self.sleep(5)
        require(False, "vm_start_not_verified")

    def stop(self):
        # Reissue the idempotent stop if the previous response was lost; verify independently.
        if self.tunnel is not None:
            try:
                self.tunnel.close()
            except Exception:
                pass  # VM shutdown must still be attempted if local tunnel cleanup fails.
        if self.status() != "TERMINATED":
            self._command("stop")
        for _ in range(12):
            if self.status() == "TERMINATED":
                return
            self.sleep(5)
        require(False, "vm_shutdown_not_verified")


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
