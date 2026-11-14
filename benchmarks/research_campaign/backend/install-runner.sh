#!/bin/bash
# Operator-only install on the EXISTING control host. Never starts the Qwen VM.
set -euo pipefail
test "$(id -u)" = 0
test "$#" = 4
bundle=$1; expected=$2; config=$3; data=$4
[[ "$expected" =~ ^[a-f0-9]{64}$ ]]
printf '%s  %s\n' "$expected" "$bundle" | sha256sum --check --status
id jewelai-mcp >/dev/null
test "$(id -Gn jewelai-mcp)" = jewelai-mcp
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv openssl
release="/opt/jewelai-research/runner-$expected"
test ! -e "$release"
install -d -o root -g root -m 755 "$release"
python3 - "$bundle" "$release" <<'PY'
import hashlib,json,sys,tarfile
from pathlib import Path
with tarfile.open(sys.argv[1]) as tar:
    members=tar.getmembers(); manifest=json.load(tar.extractfile('manifest.json'))
    assert len({m.name for m in members})==len(members)
    assert {m.name for m in members}=={*manifest['files'],'manifest.json'}
    for m in members:
        assert m.isfile() and not m.name.startswith('/') and '..' not in Path(m.name).parts
        raw=tar.extractfile(m).read()
        assert m.name=='manifest.json' or hashlib.sha256(raw).hexdigest()==manifest['files'][m.name]
        p=Path(sys.argv[2])/m.name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(raw);p.chmod(0o644)
PY
python3 -m venv "$release/venv"
"$release/venv/bin/pip" install --quiet 'mcp==2.3.0' 'google-auth[requests]==2.58.0' \
  'PyJWT[crypto]==2.15.1' 'cryptography==48.0.1' 'certifi==2026.10.23' 'uvicorn==0.38.0'
install -d -o root -g jewelai-mcp -m 750 /opt/jewelai-research/runner-data
install -o root -g jewelai-mcp -m 640 "$data/runtime.json" /opt/jewelai-research/runner-data/runtime.json
install -o root -g jewelai-mcp -m 640 "$data/model.historical.json" /opt/jewelai-research/runner-data/model.historical.json
install -o jewelai-mcp -g jewelai-mcp -m 600 "$config" /etc/jewelai-research/workspace.json
if ! test -e /etc/jewelai-research/runner-tls.key; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 365 -subj /CN=jewelai-research-internal \
    -addext subjectAltName=IP:10.203.177.2 -keyout /etc/jewelai-research/runner-tls.key \
    -out /etc/jewelai-research/runner-tls.crt 2>/dev/null
  chown root:jewelai-mcp /etc/jewelai-research/runner-tls.key
  chmod 640 /etc/jewelai-research/runner-tls.key
fi
ln -sfn "$release" /opt/jewelai-research/runner
cat >/etc/systemd/system/jewelai-research-runner.service <<'UNIT'
[Unit]
Description=JewelAI existing Native Runner MCP connection
After=network-online.target
Wants=network-online.target
[Service]
User=jewelai-mcp
Group=jewelai-mcp
Environment=PYTHONPATH=/opt/jewelai-research/runner
Environment=JEWELAI_WORKSPACE_CONFIG=/etc/jewelai-research/workspace.json
Environment=HOME=/var/lib/jewelai-research
Environment=CLOUDSDK_CONFIG=/var/lib/jewelai-research/gcloud
ExecStart=/opt/jewelai-research/runner/venv/bin/python -m jewelai_research.workspace_server
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/jewelai-research /run/jewelai-research
CapabilityBoundingSet=
StandardOutput=null
StandardError=null
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now jewelai-research-runner.service
systemctl is-active jewelai-research-runner.service
# The prior disabled Tunnel service, its symlink and historical data are untouched.
