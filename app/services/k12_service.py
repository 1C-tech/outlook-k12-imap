from __future__ import annotations

import uuid

import httpx

from ..config import settings


CHATGPT_BASE = "https://chatgpt.com"


def validate_workspace_id(workspace_id: str) -> str:
    try:
        return str(uuid.UUID(workspace_id))
    except Exception as exc:
        raise ValueError("invalid workspace id") from exc


async def request_join_workspace(access_token: str, workspace_id: str, mode: str = "request") -> dict:
    workspace_id = validate_workspace_id(workspace_id)
    endpoint = f"{CHATGPT_BASE}/backend-api/accounts/{workspace_id}/invites/request"
    payload = {"mode": mode}
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    timeout = float(settings.get("registration", {}).get("http_timeout_seconds", 30))
    proxy = str(settings.get("registration", {}).get("proxy") or "").strip() or None
    async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as client:
        resp = await client.post(endpoint, json=payload, headers=headers)
    if resp.status_code >= 400:
        return {"ok": False, "status_code": resp.status_code, "message": resp.text[:500]}
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text}
    return {"ok": True, "status_code": resp.status_code, "data": body}
