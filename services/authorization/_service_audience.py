"""Explicit Access-issued private service audience allowlist.

No Authorization application, SQL owner or provider dependencies are loaded.
"""

from __future__ import annotations

ALLOWED_AUDIENCES = frozenset(
    {
        "gateway",
        "files",
        "terminal",
        "web",
        "reverse",
        "svc",
        "infrastructure",
    }
)
