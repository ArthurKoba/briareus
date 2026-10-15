"""Bounded first-factor input; provider remains the password/PoW validator."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class NativeFirstFactorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)
    email: SecretStr = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=256)
    pow: SecretStr = Field(min_length=2, max_length=128)

    @field_validator("email")
    @classmethod
    def bounded_email(cls, value: SecretStr) -> SecretStr:
        text = value.get_secret_value()
        if text.count("@") != 1 or text != text.strip() or any(ord(c) <= 32 for c in text):
            raise ValueError("native email shape invalid")
        return value

    @field_validator("pow")
    @classmethod
    def bounded_pow(cls, value: SecretStr) -> SecretStr:
        if (
            re.fullmatch(
                r"[a-zA-Z0-9,.:/_\-&?=~#!$'()*+%]{2,128}", value.get_secret_value(), re.ASCII
            )
            is None
        ):
            raise ValueError("native proof-of-work shape invalid")
        return value
