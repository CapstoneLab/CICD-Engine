#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

# Apache currently serves only Ubuntu's default page and conflicts with the
# Compose-managed ingress on TCP 80.
if systemctl list-unit-files apache2.service >/dev/null 2>&1; then
  systemctl disable --now apache2.service
fi

if command -v ufw >/dev/null 2>&1; then
  if ufw status | grep -Fq "Status: active"; then
    ufw allow 80/tcp comment "CICD public HTTP and ACME"
    ufw allow 443/tcp comment "CICD public HTTPS"
    ufw deny 10000:19999/tcp comment "Block direct CICD app ports"
  else
    echo "UFW is inactive; rules were not enabled automatically."
    echo "App ports are still protected by their 127.0.0.1 Docker bindings."
  fi
fi

echo "Host ingress prerequisites applied. Listening sockets:"
ss -lnt '( sport = :80 or sport = :443 or ( sport >= :10000 and sport <= :19999 ) )' || true
