#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--resolve-paths" ]]; then
  echo "usage: affected-services.sh --resolve-paths" >&2
  exit 2
fi

ALL_SERVICES=(auth gateway management github gitlab files curl analysis ghidra)
PROVIDER_SERVICES=(management github gitlab files curl analysis ghidra)

declare -A affected=()

add_services() {
  local service
  for service in "$@"; do
    affected["$service"]=1
  done
}

while IFS= read -r path; do
  [[ -n "$path" ]] || continue

  case "$path" in
    Dockerfile|docker-entrypoint.sh|docker-compose.yaml|pyproject.toml|uv.lock)
      add_services "${ALL_SERVICES[@]}"
      ;;
    src/common/*)
      add_services "${ALL_SERVICES[@]}"
      ;;
    src/auth_service/*)
      add_services auth
      ;;
    src/bridge/*)
      add_services gateway
      ;;
    src/management/*)
      add_services management
      ;;
    src/modules/__init__.py)
      add_services "${PROVIDER_SERVICES[@]}"
      ;;
    src/modules/files/*)
      add_services management files curl
      ;;
    src/modules/curl/*)
      add_services curl
      ;;
    src/modules/github/*)
      add_services github
      ;;
    src/modules/gitlab/*)
      add_services gitlab
      ;;
    src/modules/analysis/*)
      add_services analysis
      ;;
    src/modules/ghidra/*)
      add_services ghidra
      ;;
    src/modules/*)
      # Unknown/new provider module: fail safe and refresh every provider runtime.
      add_services "${PROVIDER_SERVICES[@]}"
      ;;
  esac
done

service=""
for service in "${ALL_SERVICES[@]}"; do
  if [[ -n "${affected[$service]:-}" ]]; then
    printf '%s\n' "$service"
  fi
done
