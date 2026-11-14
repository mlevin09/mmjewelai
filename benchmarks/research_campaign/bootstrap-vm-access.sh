#!/bin/bash
# Operator-only bootstrap AFTER an explicit VM-start approval. Not an Agent tool.
set -euo pipefail
test "$(id -u)" = 0
test -f /tmp/jewelai-vm-access-guest.py
test -f /tmp/jewelai-research.pub
test -d /tmp/native_llm_stage1/src/native_llm_bench
test -d /tmp/jewelai_research
id jewelai-research >/dev/null 2>&1 || useradd --create-home --shell /bin/bash jewelai-research
passwd --lock jewelai-research >/dev/null
test "$(id -Gn jewelai-research)" = jewelai-research
install -d -o root -g root -m 755 /opt/jewelai-research-source
install -d -o root -g root -m 755 /usr/local/libexec
cp -a /tmp/native_llm_stage1 /opt/jewelai-research-source/
cp -a /tmp/jewelai_research /opt/jewelai-research-source/
chown -R root:jewelai-research /opt/jewelai-research-source
# cp -a can retain 0700 staging directories. Grant the dedicated research group
# read/traverse only; keep source immutable and inaccessible to other accounts.
chmod -R u=rX,g=rX,o= /opt/jewelai-research-source
install -o root -g root -m 755 /tmp/jewelai-vm-access-guest.py /usr/local/libexec/jewelai-vm-access-guest.py
install -d -o jewelai-research -g jewelai-research -m 700 /home/jewelai-research/work
chown root:root /home/jewelai-research
chmod 755 /home/jewelai-research
install -d -o root -g root -m 755 /home/jewelai-research/.ssh
key=$(cat /tmp/jewelai-research.pub)
printf 'restrict,command="/usr/bin/python3 /usr/local/libexec/jewelai-vm-access-guest.py" %s\n' "$key" >/home/jewelai-research/.ssh/authorized_keys
chown root:root /home/jewelai-research/.ssh/authorized_keys
chmod 644 /home/jewelai-research/.ssh/authorized_keys
# Model/runtime remain untouched. This account has no sudo group or GCP service account.
test "$(id -Gn jewelai-research)" = jewelai-research
