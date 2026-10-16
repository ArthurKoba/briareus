"""Offline boundaries for a one-shot, credential-free Dev native prelogin check."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "probe_dev_native_prelogin.py"
SPEC = importlib.util.spec_from_file_location("probe_dev_native_prelogin", SOURCE)
assert SPEC is not None and SPEC.loader is not None
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)

START = m.Reply(
    201,
    {"stage": "first_factor_required", "authenticated": False, "expires_in": 180},
    "application/json",
    True,
    True,
    False,
)
POW = m.Reply(
    200,
    {"challenge": "fixture-CHALLENGE-PRIVATE", "authenticated": False},
    "application/json",
    True,
    True,
    False,
)
CANCEL = m.Reply(204, None, "", True, True, False)


class FixtureTransport:
    def __init__(
        self,
        *,
        start: m.Reply = START,
        pow_reply: m.Reply = POW,
        cancel: m.Reply = CANCEL,
        cookie: bool = True,
        clear: bool = True,
    ) -> None:
        self.responses = {
            "/api/v1/auth/start": start,
            "/api/v1/auth/pow": pow_reply,
            "/api/v1/auth/cancel": cancel,
        }
        self.cookie = cookie
        self.clear = clear
        self.current = False
        self.calls: list[str] = []

    def pending(self) -> bool:
        return self.current

    def post(self, path: str) -> m.Reply:
        if path not in m.PATHS:
            raise AssertionError("unapproved operation")
        self.calls.append(path)
        reply = self.responses[path]
        if path == "/api/v1/auth/start":
            self.current = self.cookie and reply.status == 201
        elif path == "/api/v1/auth/cancel" and self.clear and reply.status == 204:
            self.current = False
        return reply


class NativeAnonymousDevProbeTests(unittest.TestCase):
    def test_one_successful_anonymous_init_pow_and_retirement(self) -> None:
        client = FixtureTransport()
        result = m.inspect(client)
        self.assertTrue(result["pass"], result)
        self.assertEqual(
            client.calls,
            ["/api/v1/auth/start", "/api/v1/auth/pow", "/api/v1/auth/cancel"],
        )
        self.assertFalse(result["user_password_or_otp_submitted"])
        self.assertFalse(result["signed_user_project_or_cedar_verified"])
        serialized = json.dumps(result)
        self.assertNotIn("fixture-CHALLENGE", serialized)
        self.assertNotIn(m.COOKIE, serialized)
        self.assertNotIn(
            "password", serialized.lower().replace("user_password_or_otp_submitted", "")
        )

    def test_only_exact_public_origin_and_three_fixed_paths(self) -> None:
        self.assertEqual(m.ORIGIN, "https://briareus.koba-nexus.ru")
        self.assertEqual(
            m.PATHS,
            frozenset({"/api/v1/auth/start", "/api/v1/auth/pow", "/api/v1/auth/cancel"}),
        )
        self.assertIsNone(m.NoRedirect().redirect_request())
        client = m.NativeAnonymousTransport()
        with self.assertRaises(ValueError):
            client.post("/auth/v1/users")
        with self.assertRaises(ValueError):
            client.post("/api/v1/auth/first-factor")

    def test_reject_initialization_without_cookie_no_pow(self) -> None:
        client = FixtureTransport(cookie=False)
        result = m.inspect(client)
        self.assertFalse(result["pass"])
        self.assertTrue(result["start_valid"])
        self.assertFalse(result["pending_cookie_scoped"])
        self.assertEqual(client.calls, ["/api/v1/auth/start"])

    def test_unexpected_initialization_response_does_not_call_pow(self) -> None:
        client = FixtureTransport(start=replace(START, status=503))
        result = m.inspect(client)
        self.assertFalse(result["pass"])
        self.assertEqual(client.calls, ["/api/v1/auth/start"])

    def test_ambiguous_or_authenticated_start_is_not_accepted_but_canceled(self) -> None:
        for data in (
            {"stage": "authenticated", "authenticated": True, "expires_in": 180},
            {"stage": "first_factor_required", "authenticated": False, "expires_in": True},
            {"stage": "first_factor_required", "authenticated": False},
            {"stage": "first_factor_required", "authenticated": False, "expires_in": 999},
        ):
            with self.subTest(data=data):
                client = FixtureTransport(start=replace(START, document=data))
                result = m.inspect(client)
                self.assertFalse(result["pass"])
                self.assertEqual(client.calls, ["/api/v1/auth/start", "/api/v1/auth/cancel"])

    def test_redirect_or_no_cache_on_start_or_pow_fails(self) -> None:
        for changed in ({"redirected": True}, {"no_store": False}, {"no_cache": False}):
            for stage in ("start", "pow"):
                with self.subTest(changed=changed, stage=stage):
                    kwargs = {stage: replace(START if stage == "start" else POW, **changed)}
                    if "pow" in kwargs:
                        kwargs["pow_reply"] = kwargs.pop("pow")
                    client = FixtureTransport(**kwargs)
                    result = m.inspect(client)
                    self.assertFalse(result["pass"])
                    self.assertEqual(client.calls[-1], "/api/v1/auth/cancel")

    def test_malformed_pow_fails_without_retry_and_cancels(self) -> None:
        for bad in (
            {"challenge": "", "authenticated": False},
            {"challenge": "valid", "authenticated": True},
            {"challenge": "unsafe\nchallenge", "authenticated": False},
            {"challenge": "valid", "authenticated": False, "secret": "leak"},
        ):
            with self.subTest(data=bad):
                client = FixtureTransport(pow_reply=replace(POW, document=bad))
                result = m.inspect(client)
                self.assertFalse(result["pass"])
                self.assertEqual(
                    client.calls,
                    ["/api/v1/auth/start", "/api/v1/auth/pow", "/api/v1/auth/cancel"],
                )

    def test_cancel_fails_closed_even_after_successful_pow(self) -> None:
        for client in (
            FixtureTransport(cancel=replace(CANCEL, status=503)),
            FixtureTransport(cancel=replace(CANCEL, redirected=True)),
            FixtureTransport(clear=False),
        ):
            with self.subTest(client=client):
                result = m.inspect(client)
                self.assertFalse(result["pass"])
                self.assertFalse(result["anonymous_transaction_retired"])

    def test_duplicate_json_keys_rejected(self) -> None:
        with self.assertRaises(ValueError):
            m._unique_pairs([("stage", "x"), ("stage", "authenticated")])


if __name__ == "__main__":
    unittest.main()
