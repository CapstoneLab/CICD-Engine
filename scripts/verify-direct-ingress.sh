#!/usr/bin/env bash
set -euo pipefail

public_host="${1:-${DEPLOY_PUBLIC_HOST:-112.186.136.153}}"
base_url="https://${public_host}/services/NekoNyangYee/Samplejavascript4"

echo "Checking trusted HTTPS certificate and deployment health: $base_url"
curl --fail --show-error --silent --location \
  --write-out '\nHTTP %{http_code}\n' \
  "${base_url}/health"

echo "Checking the repository root (the application currently decides its status):"
curl --show-error --silent --location \
  --output /dev/null --write-out 'HTTP %{http_code}\n' \
  "${base_url}/"

echo "Checking IP certificate identity:"
openssl s_client -connect "${public_host}:443" -verify_ip "${public_host}" \
  </dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -dates -ext subjectAltName

if command -v docker >/dev/null 2>&1; then
  echo "Checking restart policies:"
  docker inspect --format '{{.Name}} restart={{.HostConfig.RestartPolicy.Name}}' \
    capstone-public-ingress capstone-deploy-router \
    cicd-app-nekonyangyee-samplejavascript4-c01d5263
fi
