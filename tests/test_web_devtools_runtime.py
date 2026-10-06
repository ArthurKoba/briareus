from __future__ import annotations

import logging
import threading
import unittest

from modules.web.devtools_proxy import _DevToolsStderrForwarder, _redact_upstream_stderr


class DevToolsRuntimeTests(unittest.TestCase):
    def test_upstream_stderr_redacts_credentials(self) -> None:
        rendered = _redact_upstream_stderr(
            "failed Authorization: Bearer-secret token=abc password=hunter2"
        )
        self.assertNotIn("Bearer-secret", rendered)
        self.assertNotIn("abc", rendered)
        self.assertNotIn("hunter2", rendered)

    def test_upstream_stderr_is_forwarded_to_python_logging(self) -> None:
        event = threading.Event()
        records: list[logging.LogRecord] = []

        class Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)
                event.set()

        target_logger = logging.getLogger("mcp_bridge.web.devtools")
        handler = Capture()
        old_level = target_logger.level
        target_logger.setLevel(logging.INFO)
        target_logger.addHandler(handler)
        forwarder = _DevToolsStderrForwarder()
        try:
            forwarder.stream.write("ModuleNotFoundError: token=secret\n")
            forwarder.stream.flush()
            self.assertTrue(event.wait(1.0))
            self.assertTrue(records)
            self.assertIn("ModuleNotFoundError", records[-1].getMessage())
            self.assertNotIn("secret", records[-1].getMessage())
        finally:
            forwarder.close()
            target_logger.removeHandler(handler)
            target_logger.setLevel(old_level)
