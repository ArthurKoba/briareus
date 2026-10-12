"""Briareus single-origin thin Gateway; all /api auth belongs to Admin API."""

from __future__ import annotations

from .thin_gateway import build_app

app = build_app()

# Preserve the currently deployed ASGI_APP selector for a scoped cutover.
static_app = app
