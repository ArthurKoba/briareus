#!/bin/sh
set -eu

preview="$(printf '%s' "${ADMIN_UI_PREVIEW:-false}" | tr '[:upper:]' '[:lower:]')"

export ADMIN_UI_PREVIEW="$preview"
export ADMIN_API_BASE_URL="${ADMIN_API_BASE_URL:-}"
export ADMIN_UI_TELEMETRY_ENABLED="${ADMIN_UI_TELEMETRY_ENABLED:-true}"
export ADMIN_UI_TELEMETRY_SAMPLE_RATE="${ADMIN_UI_TELEMETRY_SAMPLE_RATE:-1}"
export ADMIN_UI_EVENTS_MODE="${ADMIN_UI_EVENTS_MODE:-websocket}"

envsubst '${ADMIN_UI_PREVIEW} ${ADMIN_API_BASE_URL} ${ADMIN_UI_TELEMETRY_ENABLED} ${ADMIN_UI_TELEMETRY_SAMPLE_RATE} ${ADMIN_UI_EVENTS_MODE}' \
    < /usr/share/nginx/html/runtime-config.template.js \
    > /usr/share/nginx/html/runtime-config.js
