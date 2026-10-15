"""Offline Terminal worker boot contract; no tools, sockets or shell execution.

A separately isolated worker may use this entrypoint to confirm minimum
kernel constraints before future scoped IPC is enabled. It is deliberately
NOT included in the current Coolify Compose or reachable from MCP.
"""

from __future__ import annotations

import sys

from modules.terminal._offline_executor import (
    OfflineExecutorUnavailable,
    require_offline_executor,
)


def main() -> int:
    try:
        require_offline_executor()
    except OfflineExecutorUnavailable:
        print("TERMINAL_OFFLINE_WORKER_ISOLATION_REQUIRED", file=sys.stderr)
        return 78
    # Kernel flags alone do not prove trusted session, owner, revoke or IPC.
    print("TERMINAL_OFFLINE_WORKER_AUTHORIZATION_UNAVAILABLE", file=sys.stderr)
    return 78


if __name__ == "__main__":
    raise SystemExit(main())
