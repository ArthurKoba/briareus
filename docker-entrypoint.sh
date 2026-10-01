#!/bin/sh
set -eu

FASTMCP_DIR="${FASTMCP_HOME:-/auth}"
MANAGEMENT_DIR="/management"
TERMINAL_WORKSPACE_DIR="${TERMINAL_WORKSPACE_ROOT:-}"
FILE_WORKSPACE_DIR="${FILE_WORKSPACE_ROOT:-}"
TERMINAL_HOME_DIR="${TERMINAL_HOME:-}"
BROWSER_PROFILE_PATH="${BROWSER_PROFILE_PATH:-}"

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
  chown -R 1000:1000 "$(dirname "${BROWSER_PROFILE_PATH}")"
fi

exec gosu 1000:1000 "$@"
