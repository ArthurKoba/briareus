#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

STATE_VOLUME="${COOLIFY_DEPLOY_STATE_VOLUME:-mcp-bridge-deploy-state}"
WAIT_TIMEOUT="${COOLIFY_DEPLOY_WAIT_TIMEOUT:-90}"
STATE_FILE="last-successful-sha"

ALL_SERVICES=(auth gateway management github gitlab files curl analysis ghidra)

docker volume create "$STATE_VOLUME" >/dev/null
STATE_DIR="$(docker volume inspect "$STATE_VOLUME" --format '{{.Mountpoint}}')"

if [[ ! -d "$STATE_DIR" ]]; then
  echo "ERROR: deploy-state volume mountpoint is not visible from this shell." >&2
  echo "Enable Coolify Preserve Repository so Custom Start Command runs on the deployment host." >&2
  exit 1
fi

CURRENT_SHA="$(git rev-parse HEAD)"
PREVIOUS_SHA=""
if [[ -f "$STATE_DIR/$STATE_FILE" ]]; then
  PREVIOUS_SHA="$(tr -d '[:space:]' < "$STATE_DIR/$STATE_FILE")"
fi

declare -a services=()
declare -a changed_files=()

if [[ -z "$PREVIOUS_SHA" ]]; then
  echo "No previous successful deployment SHA; selecting all services."
  services=("${ALL_SERVICES[@]}")
elif [[ "$PREVIOUS_SHA" == "$CURRENT_SHA" ]]; then
  echo "Commit $CURRENT_SHA is already recorded as successfully deployed."
else
  if git cat-file -e "$PREVIOUS_SHA^{commit}" 2>/dev/null; then
    mapfile -t changed_files < <(git diff --name-only "$PREVIOUS_SHA" "$CURRENT_SHA")
    mapfile -t services < <(
      printf '%s\n' "${changed_files[@]}"         | bash deploy/coolify/affected-services.sh --resolve-paths
    )
  else
    echo "Previous SHA $PREVIOUS_SHA is not available in the local Git history; selecting all services."
    services=("${ALL_SERVICES[@]}")
  fi
fi

echo "Previous successful SHA: ${PREVIOUS_SHA:-<none>}"
echo "Current SHA: $CURRENT_SHA"

if (("${#changed_files[@]}" > 0)); then
  echo "Changed files:"
  printf '  %s\n' "${changed_files[@]}"
fi

if (("${#services[@]}" == 0)); then
  echo "No runtime service is affected; skipping container recreation."
else
  echo "Affected services: ${services[*]}"
  docker compose     --env-file .env     --project-directory "$ROOT_DIR"     -f docker-compose.yaml     up -d --no-deps --wait --wait-timeout "$WAIT_TIMEOUT"     "${services[@]}"
fi

tmp="$STATE_DIR/$STATE_FILE.tmp"
printf '%s\n' "$CURRENT_SHA" > "$tmp"
mv "$tmp" "$STATE_DIR/$STATE_FILE"

echo "Recorded successful deployment SHA: $CURRENT_SHA"
