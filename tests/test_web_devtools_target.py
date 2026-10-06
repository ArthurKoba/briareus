from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from common.tool_observability import invocation_arguments_payload
from modules.web.devtools_target import (
    DevToolsTargetError,
    chrome_devtools_connection_args,
    clear_target,
    load_target,
    normalize_external_target,
    save_target,
    target_public_status,
)


class DevToolsTargetTests(unittest.TestCase):
    def test_normalizes_browser_url_and_json_version_suffix(self) -> None:
        target = normalize_external_target(
            "https://debug.example.test/session/abc/json/version?token=secret"
        )

        self.assertEqual(target.mode, "browser_url")
        self.assertEqual(
            target.endpoint,
            "https://debug.example.test/session/abc?token=secret",
        )
        self.assertEqual(
            chrome_devtools_connection_args(target),
            ["--browser-url=https://debug.example.test/session/abc?token=secret"],
        )

    def test_direct_websocket_supports_headers(self) -> None:
        target = normalize_external_target(
            "wss://debug.example.test/devtools/browser/browser-id?token=secret",
            {"Authorization": "Bearer secret"},
        )

        self.assertEqual(target.mode, "ws_endpoint")
        args = chrome_devtools_connection_args(target)
        self.assertEqual(
            args[0],
            "--ws-endpoint=wss://debug.example.test/devtools/browser/browser-id?token=secret",
        )
        self.assertIn('"Authorization":"Bearer secret"', args[1])

    def test_http_target_rejects_websocket_headers(self) -> None:
        with self.assertRaises(DevToolsTargetError):
            normalize_external_target(
                "https://debug.example.test",
                {"Authorization": "Bearer secret"},
            )

    def test_persisted_target_is_private_and_clear_restores_managed_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "target.json"
            target = normalize_external_target(
                "wss://debug.example.test/devtools/browser/browser-id",
                {"X-Debug-Token": "secret"},
            )

            save_target(target, path)
            self.assertEqual(load_target(path), target)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

            clear_target(path)
            restored = load_target(path)
            self.assertTrue(restored.managed)

    def test_public_status_never_exposes_path_query_or_header_values(self) -> None:
        target = normalize_external_target(
            "wss://debug.example.test:9443/secret/path?token=very-secret",
            {"Authorization": "Bearer very-secret"},
        )

        status = target_public_status(target)
        rendered = repr(status)
        self.assertEqual(status["endpoint_origin"], "wss://debug.example.test:9443")
        self.assertTrue(status["headers_configured"])
        self.assertNotIn("secret/path", rendered)
        self.assertNotIn("very-secret", rendered)
        self.assertNotIn("Authorization", rendered)

    def test_connect_arguments_are_omitted_from_audit(self) -> None:
        payload = invocation_arguments_payload(
            "web",
            {
                "endpoint": "wss://debug.example.test/devtools/browser/id?token=secret",
                "ws_headers": {"Authorization": "Bearer secret"},
            },
            "browser_devtools_connect",
        )

        self.assertIn("omitted", payload)
        self.assertNotIn("debug.example.test", payload)
        self.assertNotIn("Bearer secret", payload)


if __name__ == "__main__":
    unittest.main()
