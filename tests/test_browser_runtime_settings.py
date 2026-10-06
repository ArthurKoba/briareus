from __future__ import annotations

import asyncio
import unittest

from application.services import RuntimeSettingsService

from common.runtime_policy_contracts import BrowserRuntimePolicy


class _Cipher:
    def encrypt(self, plaintext: str) -> str:
        return "enc:" + plaintext[::-1]

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext.startswith("enc:"):
            raise ValueError("bad ciphertext")
        return ciphertext[4:][::-1]


class _Repository:
    def __init__(self) -> None:
        self.policy = BrowserRuntimePolicy()
        self.encrypted_token = ""

    async def get_browser_policy(self) -> BrowserRuntimePolicy:
        return self.policy.model_copy(
            update={"extension_token_configured": bool(self.encrypted_token)}
        )

    async def save_browser_policy(
        self,
        policy: BrowserRuntimePolicy,
        *,
        encrypted_extension_token: str | None = None,
        clear_extension_token: bool = False,
    ) -> BrowserRuntimePolicy:
        if clear_extension_token:
            self.encrypted_token = ""
        elif encrypted_extension_token is not None:
            self.encrypted_token = encrypted_extension_token
        self.policy = policy.model_copy(
            update={"extension_token_configured": bool(self.encrypted_token)}
        )
        return self.policy

    async def browser_extension_token(self) -> str:
        return self.encrypted_token


class BrowserRuntimeSettingsTests(unittest.TestCase):
    def test_token_is_write_only_publicly_and_available_to_launcher(self) -> None:
        async def scenario() -> None:
            repository = _Repository()
            service = RuntimeSettingsService(repository, cipher=_Cipher())  # type: ignore[arg-type]
            saved = await service.update_browser_policy(
                BrowserRuntimePolicy(
                    external_enabled=True,
                    external_mcp_url="http://192.0.2.10:8931/mcp",
                    profile_dir_name="Default",
                ),
                extension_token="top-secret",
            )
            self.assertTrue(saved.extension_token_configured)
            self.assertNotIn("top-secret", repr(saved))
            self.assertNotEqual(repository.encrypted_token, "top-secret")

            public = await service.browser_policy()
            self.assertTrue(public.extension_token_configured)
            self.assertNotIn("extension_token", public.model_dump())

            launcher = await service.browser_launcher_policy()
            self.assertEqual(launcher.extension_token, "top-secret")

            cleared = await service.update_browser_policy(
                public,
                clear_extension_token=True,
            )
            self.assertFalse(cleared.extension_token_configured)
            self.assertEqual(repository.encrypted_token, "")

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
