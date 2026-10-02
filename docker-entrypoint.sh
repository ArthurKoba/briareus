#!/bin/sh
set -eu

FASTMCP_DIR="${FASTMCP_HOME:-/auth}"
MANAGEMENT_DIR="/management"
TERMINAL_WORKSPACE_DIR="${TERMINAL_WORKSPACE_ROOT:-}"
FILE_WORKSPACE_DIR="${FILE_WORKSPACE_ROOT:-}"
TERMINAL_HOME_DIR="${TERMINAL_HOME:-}"
BROWSER_PROFILE_PATH="${BROWSER_PROFILE_PATH:-}"
BROWSER_HEADLESS="${BROWSER_HEADLESS:-false}"
BROWSER_VIEWPORT_WIDTH="${BROWSER_VIEWPORT_WIDTH:-1440}"
BROWSER_VIEWPORT_HEIGHT="${BROWSER_VIEWPORT_HEIGHT:-900}"

mkdir -p \
  "${FASTMCP_DIR}" \
  "${MANAGEMENT_DIR}" \
  /home/bridge

chown -R 1000:1000 "${FASTMCP_DIR}" "${MANAGEMENT_DIR}" /home/bridge

if [ -n "${TERMINAL_WORKSPACE_DIR}" ]; then
  mkdir -p "${TERMINAL_WORKSPACE_DIR}"
  chown 1000:1000 "${TERMINAL_WORKSPACE_DIR}"
fi

if [ -n "${FILE_WORKSPACE_DIR}" ]; then
  mkdir -p "${FILE_WORKSPACE_DIR}"
  chown 1000:1000 "${FILE_WORKSPACE_DIR}"
fi

if [ -n "${TERMINAL_HOME_DIR}" ]; then
  mkdir -p "${TERMINAL_HOME_DIR}"
  chown 1000:1000 "${TERMINAL_HOME_DIR}"
fi

if [ -n "${BROWSER_PROFILE_PATH}" ]; then
  mkdir -p "${BROWSER_PROFILE_PATH}"
  chown 1000:1000 "$(dirname "${BROWSER_PROFILE_PATH}")" "${BROWSER_PROFILE_PATH}"
  case "$(printf '%s' "${BROWSER_HEADLESS}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) ;;
    *)
      export DISPLAY="${DISPLAY:-:99}"
      gosu 1000:1000 Xvfb "${DISPLAY}" \
        -screen 0 "${BROWSER_VIEWPORT_WIDTH}x${BROWSER_VIEWPORT_HEIGHT}x24" \
        -nolisten tcp >/tmp/koba-browser-xvfb.log 2>&1 &
      display_number="${DISPLAY#:}"
      display_number="${display_number%%.*}"
      display_socket="/tmp/.X11-unix/X${display_number}"
      attempts=0
      while [ ! -S "${display_socket}" ] && [ "${attempts}" -lt 100 ]; do
        attempts=$((attempts + 1))
        sleep 0.02
      done
      if [ ! -S "${display_socket}" ]; then
        cat /tmp/koba-browser-xvfb.log >&2 || true
        echo "Xvfb did not become ready on ${DISPLAY}" >&2
        exit 1
      fi
      ;;
  esac
fi

exec gosu 1000:1000 "$@"
