"""Backend-only composition: metadata ADC, Secret Manager, durable lease, stdio tunnel."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from native_llm_bench.contracts import canonical, keys, load, require

from .vm_access import VmAccess, serve

SECRETS = {
    "tunnel": "jewelai-research-tunnel-key",
    "ssh": "jewelai-research-ssh-key",
    "authorization": "jewelai-research-activation",
}
PROJECT = "mmjewellai-preprod"


def private_file(path, data):
    """No secret in argv/environment/logs; atomic replacement with private permissions."""
    path = Path(path)
    tmp = path.with_suffix(".pending")
    fd = os.open(tmp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class ManagedSecrets:
    def __init__(self, gcloud, *, run=subprocess.run):
        self.gcloud, self.run = gcloud, run

    def read(self, name):
        require(name in SECRETS, "unknown_backend_secret")
        r = self.run(
            [
                self.gcloud,
                "secrets",
                "versions",
                "access",
                "latest",
                "--secret=" + SECRETS[name],
                "--project=" + PROJECT,
                "--verbosity=error",
                "--quiet",
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
        require(r.returncode == 0 and 0 < len(r.stdout) <= 65536, "managed_credential_unavailable")
        return r.stdout


class BackendAccess(VmAccess):
    def __init__(self, config, secrets):
        super().__init__(config)
        self.secrets = secrets

    def call(self, name, arguments):
        # A disabled/missing latest credential fails closed at each new operation.
        # Owned cleanup remains possible after activation expiry/revocation.
        if name != "vm_stop":
            self.secrets.read("tunnel")
            ssh = self.secrets.read("ssh")
            authorization = self.secrets.read("authorization")
            parsed = json.loads(authorization)
            require(isinstance(parsed, dict), "invalid_activation")
            with self.locked():
                private_file(self.config["ssh_key"], ssh)
                private_file(self.config["authorization"], canonical(parsed))
        return super().call(name, arguments)


class NativeBackendAccess(VmAccess):
    """Existing keyless/SSH boundary for narrow Runner actions, without Tunnel access."""

    def __init__(self, config, secrets):
        super().__init__(config)
        self.secrets = secrets

    def _refresh(self):
        authorization = json.loads(self.secrets.read("authorization"))
        require(isinstance(authorization, dict), "invalid_activation")
        private_file(self.config["ssh_key"], self.secrets.read("ssh"))
        private_file(self.config["authorization"], canonical(authorization))

    def call(self, name, arguments, *, expected_lease=None):
        require(name in {"vm_status", "vm_start", "vm_stop"}, "native_lifecycle_only")
        if name != "vm_stop":
            with self.locked():
                self._refresh()
        return super().call(name, arguments, expected_lease=expected_lease)

    def _guest(self, operation, arguments):
        require(
            operation in {"native_submit", "native_status", "native_result"},
            "native_guest_operation_required",
        )
        # NativeRunnerActions already holds the existing exclusive VM lock.
        self._refresh()
        if operation == "native_submit":
            from native_llm_bench.contracts import digest

            require(
                arguments.get("approval_sha256") == digest(self.lease.authorized()),
                "native_approval_changed_before_dispatch",
            )
        return super()._guest(operation, arguments)


def prepare(config, secrets):
    keys(config, ("gcloud", "client", "runtime", "state", "known_hosts", "tunnel_id"))
    require(
        re.fullmatch(r"tunnel_(?:[a-z0-9]{4}_)?[a-z0-9]{32}", config["tunnel_id"]),
        "invalid_tunnel",
    )
    runtime, state = Path(config["runtime"]), Path(config["state"])
    for p in (runtime, state):
        p.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(p.stat().st_mode & 0o077 == 0, "private_directory_required")
    private_file(runtime / "tunnel-key", secrets.read("tunnel"))
    private_file(runtime / "ssh-key", secrets.read("ssh"))
    private_file(runtime / "authorization.json", secrets.read("authorization"))
    access = {
        "gcloud": config["gcloud"],
        "state": str(state),
        "authorization": str(runtime / "authorization.json"),
        "ssh_key": str(runtime / "ssh-key"),
        "known_hosts": config["known_hosts"],
        "guest_ready": True,
    }
    private_file(runtime / "access.json", canonical(access))
    return access


def run_tunnel(config, secrets, config_path, *, run=subprocess.run):
    prepare(config, secrets)
    runtime = Path(config["runtime"])
    # Client-generated profiles contain secret file references only. The stdio child
    # reuses this same backend config and rechecks managed access on each operation.
    import shlex

    command = shlex.join(
        [sys.executable, "-m", "jewelai_research.backend", "serve", "--config", str(config_path)]
    )
    common = ["--profile", "jewelai-vm", "--profile-dir", str(runtime / "profiles")]
    for args in [
        [
            "init",
            "--force",
            "--sample",
            "sample_mcp_stdio_local",
            *common,
            "--tunnel-id",
            config["tunnel_id"],
            "--mcp-command",
            command,
            "--control-plane-api-key-ref",
            "file:" + str(runtime / "tunnel-key"),
            "--health-listen-addr",
            "127.0.0.1:0",
        ],
        ["doctor", *common],
    ]:
        result = run([config["client"], *args], capture_output=True, timeout=90, check=False)
        require(result.returncode == 0, "private_tunnel_not_ready")
    result = run(
        [config["client"], "run", *common],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    require(result.returncode == 0, "private_tunnel_disconnected")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "serve"))
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    try:
        config = load(args.config)
        secrets = ManagedSecrets(config["gcloud"])
        if args.mode == "run":
            run_tunnel(config, secrets, Path(args.config).resolve())
        else:
            access = load(Path(config["runtime"]) / "access.json")
            serve(BackendAccess(access, secrets))
    except Exception:
        # Never serialize a provider/CLI exception or its payload.
        sys.stderr.write("backend_connection_blocked\n")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
