from __future__ import annotations

import base64
import email
import hmac
import imaplib
import json
import secrets
import time
from email.header import decode_header
from hashlib import sha256
from typing import Any, Iterable

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import settings
from .code_parser import parse_verification_code


class ImapServiceError(RuntimeError):
    pass


def _b64url_decode(value: str) -> bytes:
    value += "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value.encode("ascii"))


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


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


async def exchange_graph_refresh_token(client_id: str, refresh_token: str) -> str:
    payload = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": "https://graph.microsoft.com/Mail.Read offline_access",
    }
    timeout = float(settings["imap"].get("timeout_seconds", 20))
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(settings["imap"]["token_url"], data=payload)
    if resp.status_code != 200:
        raise ImapServiceError(f"Microsoft Graph token 交换失败: HTTP {resp.status_code}")
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise ImapServiceError("Microsoft Graph token 响应缺少 access_token")
    return token


async def fetch_latest_code_graph(email_address: str, access_token: str, limit: int = 20) -> str | None:
    timeout = float(settings["imap"].get("timeout_seconds", 20))
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    params = {
        "$top": str(max(1, min(int(limit or 20), 50))),
        "$orderby": "receivedDateTime desc",
        "$select": "id,subject,from,bodyPreview,receivedDateTime",
    }
    folders = ["inbox", "junkemail"]
    async with httpx.AsyncClient(timeout=timeout) as client:
        for folder in folders:
            url = f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder}/messages"
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code >= 400:
                if folder == folders[-1]:
                    raise ImapServiceError(f"Microsoft Graph 取件失败: HTTP {resp.status_code}")
                continue
            for item in resp.json().get("value") or []:
                sender = ((item.get("from") or {}).get("emailAddress") or {}).get("address") or ""
                code = parse_verification_code(
                    subject=str(item.get("subject") or ""),
                    sender=str(sender),
                    body=str(item.get("bodyPreview") or ""),
                )
                if code:
                    return code
    return None


async def fetch_latest_code_chatai(
    email_address: str,
    client_id: str,
    refresh_token: str,
    limit: int = 20,
) -> str | None:
    base_url = str(settings.get("imap", {}).get("chatai_base_url") or "https://mail.chatai.codes").rstrip("/")
    timeout = float(settings["imap"].get("timeout_seconds", 20))
    payload = {
        "email": email_address,
        "clientId": client_id,
        "refreshToken": refresh_token,
        "keyword": "",
        "sender": "",
        "limit": max(1, min(int(limit or 20), 50)),
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        session_resp = await client.post(f"{base_url}/api/security-session", json={})
        if session_resp.status_code != 200:
            raise ImapServiceError(f"Chatai 取件会话初始化失败: HTTP {session_resp.status_code}")
        session = session_resp.json()
        if not session.get("success"):
            raise ImapServiceError(str(session.get("error") or "Chatai 取件会话初始化失败"))
        key = _b64url_decode(str(session["sessionKey"]))

        def envelope() -> dict[str, Any]:
            iv = secrets.token_bytes(12)
            nonce = _b64url_encode(secrets.token_bytes(16))
            timestamp = int(time.time() * 1000)
            ciphertext = AESGCM(key).encrypt(iv, json.dumps(payload, ensure_ascii=False).encode("utf-8"), None)
            iv_text = _b64url_encode(iv)
            cipher_text = _b64url_encode(ciphertext)
            signed_text = f"{session['sessionId']}.{nonce}.{timestamp}.{iv_text}.{cipher_text}"
            signature = _b64url_encode(hmac.new(key, signed_text.encode("utf-8"), sha256).digest())
            return {
                "secure": True,
                "sessionId": session["sessionId"],
                "sessionToken": session["sessionToken"],
                "nonce": nonce,
                "timestamp": timestamp,
                "iv": iv_text,
                "ciphertext": cipher_text,
                "signature": signature,
            }

        last_error = ""
        for endpoint in ("/api/fetch-graph", "/api/fetch-imap"):
            resp = await client.post(f"{base_url}{endpoint}", json=envelope())
            try:
                data = resp.json()
            except Exception:
                data = {"success": False, "error": resp.text[:300]}
            if resp.status_code >= 400 or not data.get("success"):
                last_error = str(data.get("error") or data.get("message") or f"HTTP {resp.status_code}")
                continue
            for item in data.get("emails") or []:
                code = parse_verification_code(
                    subject=str(item.get("subject") or ""),
                    sender=str(item.get("from") or item.get("fromName") or ""),
                    body=str(item.get("bodyText") or item.get("bodyPreview") or item.get("bodyHtml") or ""),
                )
                if code:
                    return code
        if last_error:
            raise ImapServiceError(f"Chatai 取件失败: {last_error}")
    return None


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
    auth_string = build_xoauth2_string(email_address, access_token)
    try:
        imap = imaplib.IMAP4_SSL(host, port)
        imap.authenticate("XOAUTH2", lambda _: auth_string.encode("ascii"))
    except imaplib.IMAP4.error as exc:
        raise ImapServiceError(f"Outlook IMAP 认证失败，请检查 refresh_token 是否有效且具备 IMAP 权限: {exc}") from exc
    with imap:
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
