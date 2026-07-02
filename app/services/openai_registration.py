from __future__ import annotations

import base64
import hashlib
import importlib
import asyncio
import json
import random
import secrets
import string
import sys
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..config import settings
from .imap_service import exchange_refresh_token, fetch_latest_code


AUTH_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CHATGPT_BASE = "https://chatgpt.com"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_REDIRECT_URI = "http://localhost:1455/auth/callback"
DEFAULT_SCOPE = "openid profile email offline_access"


class OpenAIRegistrationError(RuntimeError):
    pass


class PhoneVerificationRequired(OpenAIRegistrationError):
    pass


@dataclass(frozen=True)
class OAuthStart:
    auth_url: str
    state: str
    code_verifier: str
    redirect_uri: str


@dataclass(frozen=True)
class OpenAIRegistrationResult:
    verification_code: str
    token_payload: str
    access_token: str


EventCallback = Callable[[str | None, str, str], None]


def _b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _sha256_b64url_no_pad(value: str) -> str:
    return _b64url_no_pad(hashlib.sha256(value.encode("ascii")).digest())


def _pkce_verifier() -> str:
    return secrets.token_urlsafe(64)


def generate_oauth_url(redirect_uri: str = DEFAULT_REDIRECT_URI, scope: str = DEFAULT_SCOPE) -> OAuthStart:
    state = secrets.token_urlsafe(16)
    code_verifier = _pkce_verifier()
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": _sha256_b64url_no_pad(code_verifier),
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    return OAuthStart(
        auth_url=f"{AUTH_URL}?{urllib.parse.urlencode(params)}",
        state=state,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
    )


def _parse_callback_url(callback_url: str) -> dict[str, str]:
    candidate = (callback_url or "").strip()
    if not candidate:
        return {"code": "", "state": "", "error": "", "error_description": ""}
    parsed = urllib.parse.urlparse(candidate)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    fragment = urllib.parse.parse_qs(parsed.fragment, keep_blank_values=True)
    for key, values in fragment.items():
        if key not in query:
            query[key] = values

    def get_one(key: str) -> str:
        return str((query.get(key) or [""])[0] or "").strip()

    return {
        "code": get_one("code"),
        "state": get_one("state"),
        "error": get_one("error"),
        "error_description": get_one("error_description"),
    }


def _jwt_claims_no_verify(id_token: str) -> dict[str, Any]:
    if not id_token or id_token.count(".") < 2:
        return {}
    payload = id_token.split(".")[1]
    payload += "=" * ((4 - len(payload) % 4) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))
    except Exception:
        return {}


def _extract_access_token(token_payload: str) -> str:
    try:
        data = json.loads(token_payload)
    except Exception:
        return ""
    return str(data.get("access_token") or "").strip()


def _extract_next_url(data: dict[str, Any]) -> str:
    continue_url = str(data.get("continue_url") or "").strip()
    if continue_url:
        return continue_url
    page_type = str((data.get("page") or {}).get("type") or "").strip()
    return {
        "email_otp_verification": "https://auth.openai.com/email-verification",
        "sign_in_with_chatgpt_codex_consent": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
        "workspace": "https://auth.openai.com/workspace",
        "add_phone": "https://auth.openai.com/add-phone",
        "phone_verification": "https://auth.openai.com/add-phone",
        "phone_otp_verification": "https://auth.openai.com/add-phone",
        "phone_number_verification": "https://auth.openai.com/add-phone",
    }.get(page_type, "")


def _decode_jwt_segment(segment: str) -> dict[str, Any]:
    segment += "=" * ((4 - len(segment) % 4) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(segment.encode("ascii")).decode("utf-8"))
    except Exception:
        return {}


def _parse_workspace_from_auth_cookie(auth_cookie: str) -> list[dict[str, Any]]:
    if not auth_cookie or "." not in auth_cookie:
        return []
    parts = auth_cookie.split(".")
    for part in parts[:2]:
        claims = _decode_jwt_segment(part)
        workspaces = claims.get("workspaces") or []
        if isinstance(workspaces, list) and workspaces:
            return workspaces
    return []


def submit_callback_url(
    callback_url: str,
    expected_state: str,
    code_verifier: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    proxies: Any = None,
) -> str:
    parsed = _parse_callback_url(callback_url)
    if parsed["error"]:
        raise OpenAIRegistrationError(f"oauth error: {parsed['error']}: {parsed['error_description']}".strip())
    if not parsed["code"]:
        raise OpenAIRegistrationError("callback url missing code")
    if parsed["state"] != expected_state:
        raise OpenAIRegistrationError("oauth state mismatch")

    requests = _load_curl_requests()
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": parsed["code"],
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        proxies=proxies,
        verify=_ssl_verify(),
        timeout=30,
        impersonate="chrome110",
    )
    if response.status_code != 200:
        raise OpenAIRegistrationError(f"token exchange failed: HTTP {response.status_code}: {response.text[:300]}")

    body = response.json()
    access_token = str(body.get("access_token") or "").strip()
    refresh_token = str(body.get("refresh_token") or "").strip()
    id_token = str(body.get("id_token") or "").strip()
    expires_in = int(body.get("expires_in") or 0)
    claims = _jwt_claims_no_verify(id_token)
    auth_claims = claims.get("https://api.openai.com/auth") or {}
    now = int(time.time())
    payload = {
        "id_token": id_token,
        "client_id": CLIENT_ID,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "account_id": str(auth_claims.get("chatgpt_account_id") or "").strip(),
        "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "email": str(claims.get("email") or "").strip(),
        "type": "codex",
        "expired": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + max(expires_in, 0))),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _ssl_verify() -> bool:
    flag = str(settings.get("registration", {}).get("ssl_verify", True)).strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _load_curl_requests():
    try:
        from curl_cffi import requests
    except Exception as exc:
        raise OpenAIRegistrationError("curl_cffi is required for real OpenAI registration") from exc
    return requests


def _load_auth_core():
    auth_core_path = str(settings.get("registration", {}).get("auth_core_path") or "").strip()
    if auth_core_path:
        path = str(Path(auth_core_path))
        if path not in sys.path:
            sys.path.insert(0, path)
    try:
        module = importlib.import_module("utils.auth_core")
    except Exception as exc:
        raise OpenAIRegistrationError(
            "OpenAI auth_core could not be loaded. Configure registration.auth_core_path "
            "to a compatible openai-cpa checkout and run with a Python version supported by its auth_core binary."
        ) from exc
    missing = [name for name in ("generate_payload", "init_auth") if not hasattr(module, name)]
    if missing:
        raise OpenAIRegistrationError(f"OpenAI auth_core missing required functions: {', '.join(missing)}")
    return module


def _post_with_retry(session, url: str, *, headers: dict[str, Any], json_body: Any = None, proxies: Any = None):
    retries = int(settings.get("registration", {}).get("http_retries", 2))
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return session.post(
                url,
                headers=headers,
                json=json_body,
                proxies=proxies,
                verify=_ssl_verify(),
                timeout=int(settings.get("registration", {}).get("http_timeout_seconds", 30)),
            )
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise OpenAIRegistrationError(f"request failed: {last_exc}") from last_exc


def _follow_redirect_chain(session, start_url: str, proxies: Any = None, max_redirects: int = 12) -> tuple[Any, str]:
    current_url = start_url
    response = None
    for _ in range(max_redirects):
        response = session.get(
            current_url,
            allow_redirects=False,
            proxies=proxies,
            verify=_ssl_verify(),
            timeout=15,
        )
        if response.status_code not in (301, 302, 303, 307, 308):
            return response, current_url
        location = response.headers.get("Location", "")
        if not location:
            return response, current_url
        current_url = urllib.parse.urljoin(current_url, location)
        if "code=" in current_url and "state=" in current_url:
            return response, current_url
    return response, current_url


def _trace_headers() -> dict[str, str]:
    parent_id = str(random.getrandbits(64))
    return {
        "traceparent": f"00-{uuid.uuid4().hex}-{format(int(parent_id), '016x')}-01",
        "tracestate": "dd=s:1;o:rum",
        "x-datadog-origin": "rum",
        "x-datadog-parent-id": parent_id,
        "x-datadog-sampling-priority": "1",
        "x-datadog-trace-id": str(random.getrandbits(64)),
    }


def _oai_headers(did: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    headers: dict[str, Any] = {
        "accept": "application/json",
        "accept-language": "en-US,en;q=0.9",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }
    if did:
        headers["oai-device-id"] = did
    headers.update(_trace_headers())
    if extra:
        headers.update(extra)
    return headers


def _generate_user_info(username: str | None, age: int | None) -> dict[str, str]:
    name = username or "User " + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    safe_age = min(80, max(18, int(age or random.randint(18, 35))))
    year = time.gmtime().tm_year - safe_age
    return {"name": name, "birthdate": f"{year}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"}


def _proxies() -> dict[str, str] | None:
    proxy = str(settings.get("registration", {}).get("proxy") or "").strip()
    if not proxy:
        return None
    if proxy.startswith("socks5://"):
        proxy = proxy.replace("socks5://", "socks5h://", 1)
    return {"http": proxy, "https": proxy}


async def _poll_outlook_code(account: dict[str, Any], emit: EventCallback) -> str:
    attempts = int(settings.get("registration", {}).get("otp_poll_attempts", 20))
    interval = float(settings.get("registration", {}).get("otp_poll_interval_seconds", 3))
    emit("waiting_code", "Waiting for OpenAI email verification code", "INFO")
    access_token = await exchange_refresh_token(account["client_id"], account["refresh_token"])
    for attempt in range(1, attempts + 1):
        code = await asyncio.to_thread(fetch_latest_code, account["email"], access_token)
        if code:
            return code
        emit(None, f"No verification code yet ({attempt}/{attempts})", "INFO")
        await asyncio.sleep(interval)
    raise OpenAIRegistrationError("email verification code timed out")


class OpenAIRegistrationProvider:
    name = "openai"

    async def register(
        self,
        account: dict[str, Any],
        username: str | None,
        age: int | None,
        emit: EventCallback,
    ) -> OpenAIRegistrationResult:
        auth_core = _load_auth_core()
        requests = _load_curl_requests()
        proxies = _proxies()
        email = account["email"]
        password = account["password"]
        oauth = generate_oauth_url()
        session = requests.Session(proxies=proxies, impersonate="chrome")
        session.headers.update({"Connection": "close"})
        ctx: dict[str, Any] = {}
        try:
            emit("submitting", "Initializing OpenAI auth session", "INFO")
            did, user_agent = auth_core.init_auth(
                session=session,
                email=email,
                masked_email=email,
                proxies=proxies,
                verify=_ssl_verify(),
            )
            did = did or str(uuid.uuid4())

            sentinel = auth_core.generate_payload(
                did=did,
                flow="authorize_continue",
                proxy=str(settings.get("registration", {}).get("proxy") or ""),
                user_agent=user_agent,
                impersonate="chrome",
                ctx=ctx,
            )
            signup_headers = _oai_headers(
                did,
                {"Referer": "https://auth.openai.com/create-account", "content-type": "application/json"},
            )
            if sentinel:
                signup_headers["openai-sentinel-token"] = sentinel
            signup_resp = _post_with_retry(
                session,
                "https://auth.openai.com/api/accounts/authorize/continue",
                headers=signup_headers,
                json_body={"username": {"value": email, "kind": "email"}, "screen_hint": "login_or_signup"},
                proxies=proxies,
            )
            if signup_resp.status_code == 403:
                raise OpenAIRegistrationError("OpenAI rejected authorize/continue with HTTP 403")
            if signup_resp.status_code != 200:
                raise OpenAIRegistrationError(f"OpenAI authorize/continue failed: HTTP {signup_resp.status_code}")

            emit("submitting", "Submitting account password", "INFO")
            pwd_sentinel = auth_core.generate_payload(
                did=did,
                flow="username_password_create",
                proxy=str(settings.get("registration", {}).get("proxy") or ""),
                user_agent=user_agent,
                impersonate="chrome",
                ctx=ctx,
            )
            pwd_headers = _oai_headers(
                did,
                {"Referer": "https://auth.openai.com/create-account/password", "content-type": "application/json"},
            )
            if pwd_sentinel:
                pwd_headers["openai-sentinel-token"] = pwd_sentinel
            pwd_resp = _post_with_retry(
                session,
                "https://auth.openai.com/api/accounts/user/register",
                headers=pwd_headers,
                json_body={"password": password, "username": email},
                proxies=proxies,
            )
            if pwd_resp.status_code != 200:
                raise OpenAIRegistrationError(f"OpenAI password registration failed: HTTP {pwd_resp.status_code}")

            send_headers = _oai_headers(
                did,
                {"Referer": "https://auth.openai.com/create-account/password", "content-type": "application/json"},
            )
            send_sentinel = auth_core.generate_payload(
                did=did,
                flow="authorize_continue",
                proxy=str(settings.get("registration", {}).get("proxy") or ""),
                user_agent=user_agent,
                impersonate="chrome",
                ctx=ctx,
            )
            if send_sentinel:
                send_headers["openai-sentinel-token"] = send_sentinel
            _post_with_retry(
                session,
                "https://auth.openai.com/api/accounts/email-otp/send",
                headers=send_headers,
                json_body={},
                proxies=proxies,
            )

            code = await _poll_outlook_code(account, emit)
            emit("code_received", f"Received OpenAI verification code: {code}", "SUCCESS")
            val_headers = _oai_headers(
                did,
                {"Referer": "https://auth.openai.com/email-verification", "content-type": "application/json"},
            )
            val_sentinel = auth_core.generate_payload(
                did=did,
                flow="authorize_continue",
                proxy=str(settings.get("registration", {}).get("proxy") or ""),
                user_agent=user_agent,
                impersonate="chrome",
                ctx=ctx,
            )
            if val_sentinel:
                val_headers["openai-sentinel-token"] = val_sentinel
            val_resp = _post_with_retry(
                session,
                "https://auth.openai.com/api/accounts/email-otp/validate",
                headers=val_headers,
                json_body={"code": code},
                proxies=proxies,
            )
            if val_resp.status_code != 200:
                raise OpenAIRegistrationError(f"OpenAI email OTP validation failed: HTTP {val_resp.status_code}")

            next_url = _extract_next_url(val_resp.json())
            if "/add-phone" in next_url or "/select-channel" in next_url:
                raise PhoneVerificationRequired("phone_verification_required")

            emit("submitting_profile", "Submitting OpenAI profile", "INFO")
            profile_sentinel = auth_core.generate_payload(
                did=did,
                flow="create_account",
                proxy=str(settings.get("registration", {}).get("proxy") or ""),
                user_agent=user_agent,
                impersonate="chrome",
                ctx=ctx,
            )
            profile_headers = _oai_headers(
                did,
                {"Referer": "https://auth.openai.com/about-you", "content-type": "application/json"},
            )
            if profile_sentinel:
                profile_headers["openai-sentinel-token"] = profile_sentinel
            profile_resp = _post_with_retry(
                session,
                "https://auth.openai.com/api/accounts/create_account",
                headers=profile_headers,
                json_body=_generate_user_info(username, age),
                proxies=proxies,
            )
            if profile_resp.status_code != 200:
                raise OpenAIRegistrationError(f"OpenAI profile submission failed: HTTP {profile_resp.status_code}")
            next_url = _extract_next_url(profile_resp.json()) or next_url
            if "/add-phone" in next_url or "/select-channel" in next_url:
                raise PhoneVerificationRequired("phone_verification_required")

            token_payload = self._finish_oauth(session, oauth, next_url, did, proxies)
            access_token = _extract_access_token(token_payload)
            if not access_token:
                raise OpenAIRegistrationError("OAuth token payload did not include access_token")
            return OpenAIRegistrationResult(code, token_payload, access_token)
        finally:
            try:
                session.close()
            except Exception:
                pass

    def _finish_oauth(self, session, oauth: OAuthStart, next_url: str, did: str, proxies: Any) -> str:
        current_url = next_url if next_url.startswith("http") else f"https://auth.openai.com{next_url}"
        _, current_url = _follow_redirect_chain(session, current_url or oauth.auth_url, proxies)
        if "code=" in current_url and "state=" in current_url:
            return submit_callback_url(current_url, oauth.state, oauth.code_verifier, oauth.redirect_uri, proxies)

        auth_cookie = session.cookies.get("oai-client-auth-session") or ""
        workspaces = _parse_workspace_from_auth_cookie(auth_cookie)
        if workspaces:
            workspace_id = str((workspaces[0] or {}).get("id") or "").strip()
            if workspace_id:
                select_resp = _post_with_retry(
                    session,
                    "https://auth.openai.com/api/accounts/workspace/select",
                    headers=_oai_headers(did, {"Referer": current_url, "content-type": "application/json"}),
                    json_body={"workspace_id": workspace_id},
                    proxies=proxies,
                )
                if select_resp.status_code == 200:
                    final_url = _extract_next_url(select_resp.json())
                    _, current_url = _follow_redirect_chain(session, final_url, proxies)
                    if "code=" in current_url and "state=" in current_url:
                        return submit_callback_url(current_url, oauth.state, oauth.code_verifier, oauth.redirect_uri, proxies)

        _, current_url = _follow_redirect_chain(session, oauth.auth_url, proxies)
        if "code=" in current_url and "state=" in current_url:
            return submit_callback_url(current_url, oauth.state, oauth.code_verifier, oauth.redirect_uri, proxies)
        raise OpenAIRegistrationError(f"OAuth callback code was not reached; stopped at {current_url}")
