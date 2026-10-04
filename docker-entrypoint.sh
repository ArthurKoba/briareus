#!/bin/sh
set -eu

FASTMCP_DIR="${FASTMCP_HOME:-/auth}"
ADMIN_API_DIR="/admin-api"
TERMINAL_WORKSPACE_DIR="${TERMINAL_WORKSPACE_ROOT:-}"
FILE_WORKSPACE_DIR="${FILE_WORKSPACE_ROOT:-}"
TERMINAL_HOME_DIR="${TERMINAL_HOME:-}"
BROWSER_PROFILE_PATH="${BROWSER_PROFILE_PATH:-}"

mkdir -p \
  "${FASTMCP_DIR}" \
  "${ADMIN_API_DIR}" \
  /home/bridge

chown -R 1000:1000 "${FASTMCP_DIR}" "${ADMIN_API_DIR}" /home/bridge

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

GPU_RENDER_GID=""
if [ -n "${BROWSER_PROFILE_PATH}" ]; then
  mkdir -p "${BROWSER_PROFILE_PATH}"
  chown 1000:1000 "$(dirname "${BROWSER_PROFILE_PATH}")" "${BROWSER_PROFILE_PATH}"

  if [ -e /dev/dri/renderD128 ]; then
    GPU_RENDER_GID="$(stat -c '%g' /dev/dri/renderD128 2>/dev/null || true)"
  fi
fi

if [ -n "${GPU_RENDER_GID}" ] && [ "${GPU_RENDER_GID}" != "0" ] && [ "${GPU_RENDER_GID}" != "1000" ]; then
  exec setpriv --reuid=1000 --regid=1000 --groups "${GPU_RENDER_GID}" --no-new-privs "$@"
fi

exec gosu 1000:1000 "$@"
