from __future__ import annotations

import random
import secrets
import string
from dataclasses import dataclass
from typing import Any, Callable

from .openai_registration import OpenAIRegistrationProvider


@dataclass
class RegistrationSession:
    provider: str
    verification_code: str
    access_token: str
    token_payload: str | None = None


def random_profile() -> tuple[str, int]:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"user_{suffix}", random.randint(18, 35)


class MockRegistrationProvider:
    name = "mock"

    async def register(
        self,
        account: dict[str, Any],
        username: str | None,
        age: int | None,
        emit: Callable[[str | None, str, str], None],
    ) -> RegistrationSession:
        emit("submitting", "Submitting mock registration request", "INFO")
        session = await self.submit_registration(account["email"], account["password"])
        emit("waiting_code", "Waiting for mock verification code", "INFO")
        emit("code_received", f"Received mock verification code: {session.verification_code}", "SUCCESS")
        if not await self.verify_code(session, session.verification_code):
            raise RuntimeError("mock verification code validation failed")
        emit("submitting_profile", f"Submitting mock profile: {username} / {age}", "INFO")
        if not await self.submit_profile(session, username or "", int(age or 0)):
            raise RuntimeError("mock profile submission failed")
        return session

    async def submit_registration(self, email: str, password: str) -> RegistrationSession:
        return RegistrationSession(
            provider=self.name,
            verification_code=f"{random.randint(100000, 999999)}",
            access_token="mock_at_" + secrets.token_urlsafe(18),
        )

    async def verify_code(self, session: RegistrationSession, code: str) -> bool:
        return code == session.verification_code

    async def submit_profile(self, session: RegistrationSession, username: str, age: int) -> bool:
        return bool(username) and 13 <= int(age) <= 120


class OpenAIProviderAdapter:
    name = "openai"

    def __init__(self) -> None:
        self.provider = OpenAIRegistrationProvider()

    async def register(
        self,
        account: dict[str, Any],
        username: str | None,
        age: int | None,
        emit: Callable[[str | None, str, str], None],
    ) -> RegistrationSession:
        result = await self.provider.register(account, username, age, emit)
        return RegistrationSession(
            provider=self.name,
            verification_code=result.verification_code,
            access_token=result.access_token,
            token_payload=result.token_payload,
        )


def get_provider(name: str = "mock") -> MockRegistrationProvider | OpenAIProviderAdapter:
    normalized = (name or "mock").strip().lower()
    if normalized == "mock":
        return MockRegistrationProvider()
    if normalized in {"openai", "real"}:
        return OpenAIProviderAdapter()
    raise ValueError(f"unknown registration provider: {name}")
