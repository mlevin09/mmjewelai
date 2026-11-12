"""One-time LOCAL Owner setup. Never paste runtime keys into ChatGPT or command arguments."""

import getpass
import json
import os
import plistlib
import re
import shlex
import subprocess
from pathlib import Path


def main():
    root = Path.home() / "Library/Application Support/JewelAIResearchVM"
    client, command = root / "bin/tunnel-client", root / "serve"
    if not client.is_file() or not command.is_file():
        raise SystemExit("Private VM server/client installation is missing.")
    tunnel = input("Existing private OpenAI tunnel ID (not an Agent URL): ").strip()
    if not re.fullmatch(r"tunnel_[a-zA-Z0-9_-]{8,120}", tunnel):
        raise SystemExit("Invalid tunnel ID.")
    secret = getpass.getpass("Tunnel runtime key (Read + Use only; input hidden): ").strip()
    if not secret or any(c.isspace() for c in secret):
        raise SystemExit("Invalid key; nothing started.")
    key = root / "tunnel-runtime-key"
    fd = os.open(key, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(secret)
    del secret
    profiles = root / "profiles"
    args = [
        str(client),
        "init",
        "--sample",
        "sample_mcp_stdio_local",
        "--profile",
        "jewelai-vm",
        "--profile-dir",
        str(profiles),
        "--tunnel-id",
        tunnel,
        "--mcp-command",
        shlex.quote(str(command)),
        "--control-plane-api-key-ref",
        "file:" + str(key),
        "--health-listen-addr",
        "127.0.0.1:0",
    ]
    result = subprocess.run(args, capture_output=True, check=False)
    if result.returncode:
        raise SystemExit("Profile initialization failed; no VM was started. No key printed.")
    result = subprocess.run(
        [
            str(client),
            "doctor",
            "--profile",
            "jewelai-vm",
            "--profile-dir",
            str(profiles),
            "--explain",
        ],
        capture_output=True,
        check=False,
    )
    (root / "doctor.private.log").write_bytes(result.stdout + result.stderr)
    (root / "doctor.private.log").chmod(0o600)
    if result.returncode:
        raise SystemExit("Tunnel account check failed. Private diagnostic saved; no VM started.")
    label = "online.jewelai.research-vm-tunnel"
    plist = Path.home() / "Library/LaunchAgents" / (label + ".plist")
    plist.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "Label": label,
        "ProgramArguments": [
            str(client),
            "run",
            "--profile",
            "jewelai-vm",
            "--profile-dir",
            str(profiles),
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(root / "tunnel.private.log"),
        "StandardErrorPath": str(root / "tunnel.private.log"),
        "ThrottleInterval": 30,
    }
    plist.write_bytes(plistlib.dumps(data))
    plist.chmod(0o600)
    for name in ["tunnel.private.log"]:
        p = root / name
        p.touch(mode=0o600, exist_ok=True)
        p.chmod(0o600)
    result = subprocess.run(
        ["launchctl", "bootstrap", "gui/" + str(os.getuid()), str(plist)],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise SystemExit(
            "Account check passed; local service installation requires review. No VM started."
        )
    (root / "connection.json").write_text(
        json.dumps(
            {
                "name": "JewelAI VM Access",
                "tunnel_id": tunnel,
                "profile": "jewelai-vm",
                "vm_start_authorized": False,
            }
        )
        + "\n"
    )
    (root / "connection.json").chmod(0o600)
    print("Private tunnel service installed independently of Codex. VM start remains disabled.")
    print("In the existing Agent: Tools → add private custom MCP → Connection: Tunnel → select")
    print(tunnel)
    print(
        "Name: JewelAI VM Access; private/Only me; no additional MCP auth "
        "(private tunnel authenticates access)."
    )


if __name__ == "__main__":
    main()
