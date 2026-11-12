#!/bin/bash
# OPERATOR ONLY, after separate infrastructure/account activation authorization.
# No credentials in arguments; no Qwen VM start; never run from a research tool.
set -euo pipefail
test "$(id -u)" = 0
test "$#" = 4
bundle=$1
bundle_sha=$2
tunnel_id=$3
hosts=$4
[[ "$bundle_sha" =~ ^[a-f0-9]{64}$ ]]
[[ "$tunnel_id" =~ ^tunnel_([a-z0-9]{4}_)?[a-z0-9]{32}$ ]]
printf '%s  %s\n' "$bundle_sha" "$bundle" | sha256sum --check --status
grep -q '^jewelai-llm-lab ' "$hosts"
. /etc/os-release
test "$ID" = ubuntu
test "$VERSION_ID" = 24.04
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 ca-certificates curl gnupg unzip openssh-client
if ! command -v gcloud >/dev/null; then
  curl --fail --silent --show-error https://packages.cloud.google.com/apt/doc/apt-key.gpg -o /tmp/jewelai-google.gpg
  gpg --dearmor --yes -o /usr/share/keyrings/jewelai-google.gpg /tmp/jewelai-google.gpg
  rm /tmp/jewelai-google.gpg
  printf '%s\n' 'deb [signed-by=/usr/share/keyrings/jewelai-google.gpg] https://packages.cloud.google.com/apt cloud-sdk main' >/etc/apt/sources.list.d/jewelai-google.list
  apt-get update -qq
  apt-get install -y -qq google-cloud-cli
fi
id jewelai-mcp >/dev/null 2>&1 || useradd --system --home-dir /var/lib/jewelai-research --shell /usr/sbin/nologin jewelai-mcp
test "$(id -Gn jewelai-mcp)" = jewelai-mcp
install -d -o root -g jewelai-mcp -m 750 /etc/jewelai-research
install -d -o root -g root -m 755 /opt/jewelai-research
release="/opt/jewelai-research/$bundle_sha"
test ! -e "$release"
install -d -o root -g root -m 755 "$release"
python3 - "$bundle" "$release" <<'PY'
import hashlib,json,sys,tarfile
from pathlib import Path
with tarfile.open(sys.argv[1]) as tar:
    members=tar.getmembers()
    manifest=json.load(tar.extractfile('manifest.json'))
    assert len({m.name for m in members})==len(members)
    assert {m.name for m in members} == {*manifest['files'], 'manifest.json'}
    for m in members:
        assert m.isfile() and not m.name.startswith('/') and '..' not in Path(m.name).parts
        data=tar.extractfile(m).read()
        assert m.name=='manifest.json' or hashlib.sha256(data).hexdigest()==manifest['files'][m.name]
        p=Path(sys.argv[2])/m.name
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(data);p.chmod(0o644)
PY
curl --fail --silent --show-error --location \
  https://github.com/openai/tunnel-client/releases/download/v0.0.20/tunnel-client-v0.0.20-linux-amd64.zip \
  -o "$release/tunnel.zip"
printf '%s  %s\n' 2f06ce5a17425c74a827e7038692936e973ae388e7eec728c40efee1fb5f139d "$release/tunnel.zip" | sha256sum --check --status
unzip -q "$release/tunnel.zip" -d "$release/client"
test -f "$release/client/tunnel-client"
test -f "$release/client/cloudflared"
chmod 755 "$release/client/tunnel-client" "$release/client/cloudflared"
rm "$release/tunnel.zip"
install -o root -g jewelai-mcp -m 640 "$hosts" /etc/jewelai-research/known_hosts
python3 - "$tunnel_id" "$release/client/tunnel-client" <<'PY'
import json,os,sys
from pathlib import Path
config={'gcloud':'/usr/bin/gcloud','client':sys.argv[2],
        'runtime':'/run/jewelai-research','state':'/var/lib/jewelai-research/lease',
        'known_hosts':'/etc/jewelai-research/known_hosts','tunnel_id':sys.argv[1]}
p=Path('/etc/jewelai-research/backend.json')
p.write_text(json.dumps(config)+'\n');p.chmod(0o640)
import grp
os.chown(p,0,grp.getgrnam('jewelai-mcp').gr_gid)
PY
systemctl stop jewelai-research-connection.service 2>/dev/null || true
ln -sfn "$release" /opt/jewelai-research/server
install -o root -g root -m 644 "$(dirname "$0")/jewelai-research-connection.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now jewelai-research-connection.service
printf '%s\n' 'Backend installed; inspect systemd status. No Qwen VM was started.'
