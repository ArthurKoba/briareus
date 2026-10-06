from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import SplitResult, urlsplit, urlunsplit

from common.models import JsonObject

MANAGED_BROWSER_URL = "http://127.0.0.1:9222"
_TARGET_FILE_ENV = "BROWSER_DEVTOOLS_TARGET_PATH"
_DEFAULT_TARGET_FILE = Path("/tmp/koba-devtools-target.json")
_MAX_ENDPOINT_CHARS = 8192
_MAX_HEADER_COUNT = 32
_MAX_HEADER_NAME_CHARS = 128
_MAX_HEADER_VALUE_CHARS = 4096


class DevToolsTargetError(ValueError):
    """External Chrome DevTools target configuration is invalid."""


@dataclass(frozen=True, slots=True)
class DevToolsTarget:
    mode: Literal["managed", "browser_url", "ws_endpoint"]
    endpoint: str
    ws_headers: dict[str, str]

    @property
    def managed(self) -> bool:
        return self.mode == "managed"


def target_config_path() -> Path:
    raw = os.environ.get(_TARGET_FILE_ENV, "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_TARGET_FILE


def _normalized_headers(headers: dict[str, str] | None) -> dict[str, str]:
    if headers is None:
        return {}
    if len(headers) > _MAX_HEADER_COUNT:
        raise DevToolsTargetError(f"at most {_MAX_HEADER_COUNT} WebSocket headers are allowed")
    normalized: dict[str, str] = {}
    for raw_name, raw_value in headers.items():
        name = str(raw_name).strip()
        value = str(raw_value).strip()
        if not name or len(name) > _MAX_HEADER_NAME_CHARS:
            raise DevToolsTargetError("WebSocket header name is empty or too long")
        if len(value) > _MAX_HEADER_VALUE_CHARS:
            raise DevToolsTargetError(f"WebSocket header value is too long: {name}")
        if "\r" in name or "\n" in name or "\r" in value or "\n" in value:
            raise DevToolsTargetError("WebSocket headers cannot contain CR/LF characters")
        normalized[name] = value
    return normalized


def _without_json_version(parts: SplitResult) -> SplitResult:
    path = parts.path.rstrip("/")
    if path.endswith("/json/version"):
        path = path[: -len("/json/version")]
    return parts._replace(path=path)


def normalize_external_target(
    endpoint: str,
    ws_headers: dict[str, str] | None = None,
) -> DevToolsTarget:
    value = endpoint.strip()
    if not value:
        raise DevToolsTargetError("external DevTools endpoint is required")
    if len(value) > _MAX_ENDPOINT_CHARS:
        raise DevToolsTargetError("external DevTools endpoint is too long")

    parts = urlsplit(value)
    scheme = parts.scheme.casefold()
    if scheme not in {"http", "https", "ws", "wss"}:
        raise DevToolsTargetError("endpoint must use http, https, ws, or wss")
    if not parts.hostname:
        raise DevToolsTargetError("endpoint must include a host")
    if parts.fragment:
        raise DevToolsTargetError("endpoint fragments are not supported")

    headers = _normalized_headers(ws_headers)
    if scheme in {"http", "https"}:
        if headers:
            raise DevToolsTargetError("WebSocket headers require a ws/wss endpoint")
        normalized = _without_json_version(parts)
        return DevToolsTarget(
            mode="browser_url",
            endpoint=urlunsplit(normalized).rstrip("/"),
            ws_headers={},
        )

    return DevToolsTarget(mode="ws_endpoint", endpoint=value, ws_headers=headers)


def managed_target() -> DevToolsTarget:
    return DevToolsTarget(mode="managed", endpoint=MANAGED_BROWSER_URL, ws_headers={})


def load_target(path: Path | None = None) -> DevToolsTarget:
    target_path = path or target_config_path()
    try:
        payload = json.loads(target_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return managed_target()
    except (OSError, json.JSONDecodeError) as exc:
        raise DevToolsTargetError("external DevTools target file is unreadable") from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise DevToolsTargetError("external DevTools target file has an unsupported format")
    endpoint = payload.get("endpoint")
    headers = payload.get("ws_headers")
    if not isinstance(endpoint, str):
        raise DevToolsTargetError("external DevTools target file has no endpoint")
    if headers is not None and not isinstance(headers, dict):
        raise DevToolsTargetError("external DevTools target headers are invalid")
    typed_headers = None if headers is None else {str(k): str(v) for k, v in headers.items()}
    return normalize_external_target(endpoint, typed_headers)


def save_target(target: DevToolsTarget, path: Path | None = None) -> None:
    if target.managed:
        clear_target(path)
        return
    target_path = path or target_config_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = target_path.with_suffix(target_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "version": 1,
                "endpoint": target.endpoint,
                "ws_headers": target.ws_headers,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(target_path)


def clear_target(path: Path | None = None) -> None:
    target_path = path or target_config_path()
    try:
        target_path.unlink()
    except FileNotFoundError:
        return


def chrome_devtools_connection_args(target: DevToolsTarget) -> list[str]:
    if target.mode in {"managed", "browser_url"}:
        return [f"--browser-url={target.endpoint}"]
    result = [f"--ws-endpoint={target.endpoint}"]
    if target.ws_headers:
        result.append(
            "--ws-headers="
            + json.dumps(target.ws_headers, ensure_ascii=False, separators=(",", ":"))
        )
    return result


def browser_version_url(target: DevToolsTarget) -> str:
    if target.mode != "browser_url":
        raise DevToolsTargetError("browser version URL requires an http/https endpoint")
    parts = urlsplit(target.endpoint)
    path = parts.path.rstrip("/") + "/json/version"
    return urlunsplit(parts._replace(path=path))


def target_public_status(target: DevToolsTarget) -> JsonObject:
    if target.managed:
        return {
            "mode": "managed",
            "endpoint_kind": "browser_url",
            "endpoint_origin": "managed Chromium",
            "headers_configured": False,
        }
    parts = urlsplit(target.endpoint)
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port is not None else ""
    return {
        "mode": "external",
        "endpoint_kind": target.mode,
        "endpoint_origin": f"{parts.scheme}://{host}{port}",
        "headers_configured": bool(target.ws_headers),
    }
