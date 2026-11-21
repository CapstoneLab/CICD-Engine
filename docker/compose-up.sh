#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:-existing}"
replace_existing="${2:-}"
backend_container="${BACKEND_CONTAINER_NAME:-capstone-back}"
network_name="${CAPSTONE_NETWORK_NAME:-capstone-internal}"
engine_data_root="${ENGINE_DATA_ROOT:-$repo_root/.docker-data}"
backend_env_file="${BACKEND_ENV_FILE:-$repo_root/.env.backend}"

mkdir -p "$engine_data_root/runs" "$engine_data_root/workspace"

if ! docker network inspect "$network_name" >/dev/null 2>&1; then
  docker network create "$network_name" >/dev/null
  echo "Created Docker network: $network_name"
fi

compose() {
  ENGINE_DATA_ROOT="$engine_data_root" \
  CAPSTONE_NETWORK_NAME="$network_name" \
  BACKEND_CONTAINER_NAME="$backend_container" \
  docker compose --project-directory "$repo_root" -f "$repo_root/compose.yaml" "$@"
}

case "$mode" in
  existing)
    if ! docker inspect "$backend_container" >/dev/null 2>&1; then
      echo "Running backend container not found: $backend_container" >&2
      echo "Use '$0 managed' after preparing .env.backend instead." >&2
      exit 1
    fi

    if ! docker inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' \
      "$backend_container" | grep -Fxq "$network_name"; then
      docker network connect --alias backend "$network_name" "$backend_container"
      echo "Connected $backend_container to $network_name as backend."
    fi

    compose up -d --build cicd-engine public-ingress
    ;;

  managed)
    if [[ ! -f "$backend_env_file" ]]; then
      if docker inspect "$backend_container" >/dev/null 2>&1; then
        "$repo_root/docker/migrate-backend-env.sh" "$backend_container" "$backend_env_file"
      else
        echo "Missing backend env file: $backend_env_file" >&2
        exit 1
      fi
    fi

    if docker inspect "$backend_container" >/dev/null 2>&1; then
      compose_project="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$backend_container")"
      if [[ "$compose_project" != "capstone-cicd" ]]; then
        if [[ "$replace_existing" != "--replace-existing" ]]; then
          echo "Container $backend_container is not managed by this Compose project." >&2
          echo "Re-run with: $0 managed --replace-existing" >&2
          exit 1
        fi
        docker stop "$backend_container" >/dev/null
        docker rm "$backend_container" >/dev/null
        echo "Replaced legacy backend container: $backend_container"
      fi
    fi

    BACKEND_ENV_FILE="$backend_env_file" compose --profile managed-backend up -d --build
    ;;

  *)
    echo "Usage: $0 [existing|managed] [--replace-existing]" >&2
    exit 2
    ;;
esac

compose ps
