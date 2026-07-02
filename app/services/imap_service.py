from __future__ import annotations

import base64
import email
import imaplib
from email.header import decode_header
from typing import Iterable

import httpx

from ..config import settings
from .code_parser import parse_verification_code


class ImapServiceError(RuntimeError):
    pass


def build_xoauth2_string(email_address: str, access_token: str) -> str:
    return f"user={email_address}\x01auth=Bearer {access_token}\x01\x01"


async def exchange_refresh_token(client_id: str, refresh_token: str) -> str:
    payload = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
    }
    timeout = float(settings["imap"].get("timeout_seconds", 20))
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(settings["imap"]["token_url"], data=payload)
    if resp.status_code != 200:
        raise ImapServiceError(f"Outlook token 交换失败: HTTP {resp.status_code}")
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise ImapServiceError("Outlook token 响应缺少 access_token")
    return token


def _decode(value: str | bytes | None) -> str:
    if not value:
        return ""
    fragments = decode_header(value)
    result = ""
    for fragment, charset in fragments:
        if isinstance(fragment, bytes):
            result += fragment.decode(charset or "utf-8", errors="replace")
        else:
            result += fragment
    return result


def _message_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        parts = []
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_type() in {"text/plain", "text/html"}:
                payload = part.get_payload(decode=True) or b""
                parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
        return "\n".join(parts)
    payload = msg.get_payload(decode=True) or b""
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")


def fetch_latest_code(email_address: str, access_token: str, folders: Iterable[str] | None = None) -> str | None:
    host = settings["imap"]["host"]
    port = int(settings["imap"]["port"])
    folders = list(folders or settings["imap"].get("folders") or ["INBOX"])
    auth_bytes = base64.b64encode(build_xoauth2_string(email_address, access_token).encode()).decode()
    with imaplib.IMAP4_SSL(host, port) as imap:
        imap.authenticate("XOAUTH2", lambda _: auth_bytes)
        for folder in folders:
            imap.select(folder)
            typ, data = imap.search(None, "ALL")
            if typ != "OK" or not data or not data[0]:
                continue
            ids = data[0].split()[-20:]
            for msg_id in reversed(ids):
                typ, msg_data = imap.fetch(msg_id, "(RFC822)")
                if typ != "OK" or not msg_data:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                code = parse_verification_code(
                    subject=_decode(msg.get("Subject")),
                    sender=_decode(msg.get("From")),
                    body=_message_body(msg),
                )
                if code:
                    return code
    return None
