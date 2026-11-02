#!/bin/bash
# Disable password SSH after key login is confirmed. Idempotent.
set -euo pipefail
cp -a /etc/ssh/sshd_config "/etc/ssh/sshd_config.bak.vpn.$(date +%s)"
if grep -qE '^PasswordAuthentication' /etc/ssh/sshd_config; then
  sed -i 's/^PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
else
  echo 'PasswordAuthentication no' >> /etc/ssh/sshd_config
fi
if grep -qE '^KbdInteractiveAuthentication' /etc/ssh/sshd_config; then
  sed -i 's/^KbdInteractiveAuthentication.*/KbdInteractiveAuthentication no/' /etc/ssh/sshd_config
else
  echo 'KbdInteractiveAuthentication no' >> /etc/ssh/sshd_config
fi
if grep -qE '^ChallengeResponseAuthentication' /etc/ssh/sshd_config; then
  sed -i 's/^ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' /etc/ssh/sshd_config
fi
if grep -qE '^PermitRootLogin' /etc/ssh/sshd_config; then
  sed -i 's/^PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
else
  echo 'PermitRootLogin prohibit-password' >> /etc/ssh/sshd_config
fi
sshd -t
if systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null; then
  echo SSHD_RELOADED
else
  echo SSHD_RELOAD_FAIL
  exit 1
fi
grep -E '^(PasswordAuthentication|PermitRootLogin|KbdInteractiveAuthentication)' /etc/ssh/sshd_config
