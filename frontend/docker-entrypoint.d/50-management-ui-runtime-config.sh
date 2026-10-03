#!/bin/sh
set -eu

preview="$(printf '%s' "${MANAGEMENT_UI_PREVIEW:-false}" | tr '[:upper:]' '[:lower:]')"

if [ "$preview" != "true" ] && [ -z "${MANAGEMENT_BACKEND_ORIGIN:-}" ]; then
    echo "MANAGEMENT_BACKEND_ORIGIN is required when MANAGEMENT_UI_PREVIEW is not true" >&2
    exit 1
fi

if [ -z "${MANAGEMENT_BACKEND_ORIGIN:-}" ]; then
    export MANAGEMENT_BACKEND_ORIGIN="http://127.0.0.1:9"
fi

export MANAGEMENT_UI_PREVIEW="$preview"
export MANAGEMENT_UI_TELEMETRY_ENABLED="${MANAGEMENT_UI_TELEMETRY_ENABLED:-true}"
export MANAGEMENT_UI_TELEMETRY_ENDPOINT="${MANAGEMENT_UI_TELEMETRY_ENDPOINT:-/api/telemetry}"
export MANAGEMENT_UI_TELEMETRY_SAMPLE_RATE="${MANAGEMENT_UI_TELEMETRY_SAMPLE_RATE:-1}"
export MANAGEMENT_UI_EVENTS_MODE="${MANAGEMENT_UI_EVENTS_MODE:-hybrid}"
export MANAGEMENT_UI_EVENTS_URL="${MANAGEMENT_UI_EVENTS_URL:-/api/realtime}"

envsubst '${MANAGEMENT_UI_PREVIEW} ${MANAGEMENT_UI_TELEMETRY_ENABLED} ${MANAGEMENT_UI_TELEMETRY_ENDPOINT} ${MANAGEMENT_UI_TELEMETRY_SAMPLE_RATE} ${MANAGEMENT_UI_EVENTS_MODE} ${MANAGEMENT_UI_EVENTS_URL}' \
    < /usr/share/nginx/html/runtime-config.template.js \
    > /usr/share/nginx/html/runtime-config.js
