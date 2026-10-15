"""Necessary kernel preflight for legacy Terminal subprocess entrypoints.

This does NOT create a namespace or prove a Project sandbox. An approved
separately deployed worker must already have a read-only root, non-root UID,
no Linux capabilities, no-new-privileges, and only loopback networking.
Nothing in a JSON tool request or environment variable can waive this gate.
The current networked Hand controller necessarily fails these checks.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


class OfflineExecutorUnavailable(RuntimeError):
    """A legacy subprocess may not run in the Hand's trusted controller."""


def _reject() -> None:
    raise OfflineExecutorUnavailable("TERMINAL_OFFLINE_EXECUTOR_NOT_ISOLATED")


def require_offline_executor() -> None:
    """Refuse shell startup unless conservative local kernel facts are visible.

    These facts are NECESSARY, never SUFFICIENT: deployment still needs
    separately verified network namespace, private mounts/IPC, cgroups,
    supervisor identity, live Cedar grants, and revocation enforcement.
    """
    if sys.platform != "linux" or os.geteuid() == 0:
        _reject()
    try:
        status = Path("/proc/self/status").read_text(encoding="ascii")
        fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
        if (
            fields.get("NoNewPrivs", "").strip() != "1"
            or int(fields.get("CapEff", "").strip(), 16) != 0
            or not (os.statvfs("/").f_flag & os.ST_RDONLY)
        ):
            _reject()

        # This is intentionally more restrictive than "no default route":
        # a LAN address without a default route can still reach private
        # Postgres, Valkey and Rauthy services.
        interfaces = {entry.name for entry in Path("/sys/class/net").iterdir()}
        if interfaces != {"lo"}:
            _reject()
        route_lines = Path("/proc/net/route").read_text(encoding="ascii").splitlines()
        if not route_lines or any(
            len(line.split()) < 11 or line.split()[0] != "lo" for line in route_lines[1:]
        ):
            _reject()
        # IPv6 routes can also reach unrelated internal resources.
        for line in Path("/proc/net/ipv6_route").read_text(encoding="ascii").splitlines():
            parts = line.split()
            if len(parts) < 10 or parts[-1] != "lo":
                _reject()
    except (OSError, UnicodeError, ValueError, IndexError):
        _reject()
