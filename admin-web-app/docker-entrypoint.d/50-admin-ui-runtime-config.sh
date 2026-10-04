#!/bin/sh
set -eu

preview="$(printf '%s' "${ADMIN_UI_PREVIEW:-false}" | tr '[:upper:]' '[:lower:]')"

export ADMIN_UI_PREVIEW="$preview"
export ADMIN_UI_TELEMETRY_ENABLED="${ADMIN_UI_TELEMETRY_ENABLED:-true}"
export ADMIN_UI_TELEMETRY_ENDPOINT="${ADMIN_UI_TELEMETRY_ENDPOINT:-/api/telemetry}"
export ADMIN_UI_TELEMETRY_SAMPLE_RATE="${ADMIN_UI_TELEMETRY_SAMPLE_RATE:-1}"
export ADMIN_UI_EVENTS_MODE="${ADMIN_UI_EVENTS_MODE:-hybrid}"
export ADMIN_UI_EVENTS_URL="${ADMIN_UI_EVENTS_URL:-/api/realtime}"

envsubst '${ADMIN_UI_PREVIEW} ${ADMIN_UI_TELEMETRY_ENABLED} ${ADMIN_UI_TELEMETRY_ENDPOINT} ${ADMIN_UI_TELEMETRY_SAMPLE_RATE} ${ADMIN_UI_EVENTS_MODE} ${ADMIN_UI_EVENTS_URL}' \
    < /usr/share/nginx/html/runtime-config.template.js \
    > /usr/share/nginx/html/runtime-config.js
