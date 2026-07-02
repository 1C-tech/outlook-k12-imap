from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from fastapi import Header, HTTPException

from .config import settings


@dataclass
class TokenRecord:
    token: str
    expires_at: float


_tokens: dict[str, TokenRecord] = {}


def login_with_password(password: str) -> str:
    if password != settings["auth"]["admin_password"]:
        raise HTTPException(status_code=401, detail="Invalid password")
    token = secrets.token_urlsafe(32)
    ttl = int(settings["auth"].get("token_ttl_seconds", 86400))
    _tokens[token] = TokenRecord(token=token, expires_at=time.time() + ttl)
    return token


def revoke_token(token: str) -> None:
    _tokens.pop(token, None)


def verify_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return verify_token_value(authorization.split(" ", 1)[1].strip())


def verify_token_value(token: str | None) -> str:
    token = (token or "").strip()
    record = _tokens.get(token)
    if not record or record.expires_at < time.time():
        _tokens.pop(token, None)
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return token
