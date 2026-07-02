from __future__ import annotations

import json

from ..config import settings
from ..database import connect, write_lock
from .account_service import (
    ACCOUNT_STATUS_INVITED,
    ACCOUNT_STATUS_REGISTERED_NOT_INVITED,
    get_account,
    list_account_ids_by_status,
    update_account,
)
from .k12_service import request_join_workspace, validate_workspace_id
from .log_service import write_log
from .registration_provider import get_provider, random_profile


STATUSES = [
    "pending",
    "submitting",
    "waiting_code",
    "code_received",
    "submitting_profile",
    "k12_inviting",
    "success",
    "failed",
    "stopped",
]


def create_tasks(account_ids: list[int], username: str | None = None, age: int | None = None) -> list[int]:
    task_ids: list[int] = []
    created_logs: list[tuple[int, int, str]] = []
    workspace_id = settings["k12"]["workspace_id"]
    validate_workspace_id(workspace_id)
    with write_lock():
        with connect() as conn:
            for account_id in account_ids:
                row = conn.execute(
                    "SELECT id, email FROM ms_accounts WHERE id = ?",
                    (int(account_id),),
                ).fetchone()
                if not row:
                    continue
                account = dict(row)
                item_username, item_age = (username, age) if username and age else random_profile()
                cur = conn.execute(
                    """
                    INSERT INTO reg_tasks(account_id, email, username, age, workspace_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (account["id"], account["email"], item_username, item_age, workspace_id),
                )
                task_id = int(cur.lastrowid)
                task_ids.append(task_id)
                created_logs.append((task_id, account["id"], account["email"]))
    for task_id, account_id, email in created_logs:
        write_log("INFO", "Registration task created", task_id=task_id, account_id=account_id, email=email)
    return task_ids


async def run_task_ids_concurrently(task_ids: list[int], concurrency: int | None = None) -> dict:
    max_concurrency = int(concurrency or settings["registration"].get("concurrency", 1) or 1)
    max_concurrency = max(1, min(50, max_concurrency))

    import asyncio

    semaphore = asyncio.Semaphore(max_concurrency)

    async def run_one(task_id: int) -> dict:
        async with semaphore:
            return await run_task(task_id)

    results = await asyncio.gather(*(run_one(task_id) for task_id in task_ids), return_exceptions=True)
    failed = sum(1 for item in results if isinstance(item, Exception) or (isinstance(item, dict) and item.get("status") == "failed"))
    return {
        "task_ids": task_ids,
        "completed": len(task_ids),
        "failed": failed,
        "concurrency": max_concurrency,
    }


def create_tasks_by_account_status(status: int, limit: int | None = None) -> dict:
    account_ids = list_account_ids_by_status(status, limit)
    task_ids = create_tasks(account_ids)
    return {"account_ids": account_ids, "task_ids": task_ids, "created": len(task_ids)}


def _extract_access_token(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if raw.startswith("{"):
        try:
            return str((json.loads(raw) or {}).get("access_token") or "").strip()
        except Exception:
            return ""
    return raw


def latest_account_access_token(account_id: int) -> str:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT access_token
            FROM reg_tasks
            WHERE account_id = ? AND access_token IS NOT NULL AND access_token != ''
            ORDER BY id DESC
            LIMIT 1
            """,
            (int(account_id),),
        ).fetchone()
    return _extract_access_token(row["access_token"] if row else "")


async def run_invite_for_account(account_id: int) -> dict:
    account = get_account(account_id, include_secret=True)
    if not account:
        raise ValueError("account not found")
    workspace_id = settings["k12"]["workspace_id"]
    validate_workspace_id(workspace_id)
    write_log("INFO", "开始补发 K12 邀请", account_id=account["id"], email=account["email"])
    access_token = latest_account_access_token(account["id"])
    if not access_token:
        update_account(account["id"], remark="缺少可用 OpenAI access_token，无法补邀请")
        write_log("ERROR", "缺少可用 OpenAI access_token，无法补邀请", account_id=account["id"], email=account["email"])
        return {"account_id": account["id"], "ok": False, "error": "missing_access_token"}
    if access_token.startswith("mock_at_") or settings["registration"].get("provider") == "mock":
        update_account(account["id"], status=ACCOUNT_STATUS_INVITED, remark="Mock 模式已标记邀请成功")
        write_log("SUCCESS", "Mock 模式已标记 K12 邀请成功", account_id=account["id"], email=account["email"])
        return {"account_id": account["id"], "ok": True, "mock": True}
    invite_result = await request_join_workspace(
        access_token,
        workspace_id,
        settings["k12"].get("invite_mode", "request"),
    )
    if not invite_result.get("ok"):
        message = f"补发 K12 邀请失败: HTTP {invite_result.get('status_code')} {invite_result.get('message')}"
        update_account(account["id"], remark=message)
        write_log("ERROR", message, account_id=account["id"], email=account["email"])
        return {"account_id": account["id"], "ok": False, "error": message}
    update_account(account["id"], status=ACCOUNT_STATUS_INVITED, remark=None)
    write_log("SUCCESS", "K12 邀请补发成功", account_id=account["id"], email=account["email"])
    return {"account_id": account["id"], "ok": True}


async def run_unfinished_accounts(concurrency: int | None = None) -> dict:
    import asyncio

    register_account_ids = list_account_ids_by_status(0)
    invite_account_ids = list_account_ids_by_status(1)
    task_ids = create_tasks(register_account_ids)
    max_concurrency = int(concurrency or settings["registration"].get("concurrency", 1) or 1)
    max_concurrency = max(1, min(50, max_concurrency))
    semaphore = asyncio.Semaphore(max_concurrency)

    async def guarded(coro):
        async with semaphore:
            return await coro

    register_jobs = [guarded(run_task(task_id)) for task_id in task_ids]
    invite_jobs = [guarded(run_invite_for_account(account_id)) for account_id in invite_account_ids]
    results = await asyncio.gather(*register_jobs, *invite_jobs, return_exceptions=True)
    failed = sum(
        1
        for item in results
        if isinstance(item, Exception)
        or (isinstance(item, dict) and item.get("status") == "failed")
        or (isinstance(item, dict) and item.get("ok") is False)
    )
    return {
        "registration_account_ids": register_account_ids,
        "invite_account_ids": invite_account_ids,
        "task_ids": task_ids,
        "created": len(task_ids),
        "invite_count": len(invite_account_ids),
        "failed": failed,
        "concurrency": max_concurrency,
    }


def get_task(task_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM reg_tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None


def list_tasks(page: int = 1, page_size: int = 50, status: str | None = None, email: str | None = None) -> dict:
    page = max(1, int(page))
    page_size = min(200, max(1, int(page_size)))
    where = []
    params: list = []
    if status:
        where.append("status = ?")
        params.append(status)
    if email:
        where.append("email LIKE ?")
        params.append(f"%{email}%")
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM reg_tasks {where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM reg_tasks {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
    return {"data": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}


def update_task_status(task_id: int, status: str, **fields) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status}")
    updates = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
    params: list = [status]
    for key, value in fields.items():
        updates.append(f"{key} = ?")
        params.append(value)
    with write_lock():
        with connect() as conn:
            conn.execute(f"UPDATE reg_tasks SET {', '.join(updates)} WHERE id = ?", [*params, task_id])


async def run_task(task_id: int) -> dict:
    task = get_task(task_id)
    if not task:
        raise ValueError("task not found")
    account = get_account(task["account_id"], include_secret=True)
    if not account:
        raise ValueError("account not found")
    provider = get_provider(settings["registration"]["provider"])

    def emit(status: str | None, message: str, level: str = "INFO") -> None:
        if status:
            update_task_status(task_id, status)
        write_log(level, message, task_id, account["id"], account["email"])

    try:
        session = await provider.register(account, task["username"], int(task["age"]), emit)
        update_account(account["id"], status=ACCOUNT_STATUS_REGISTERED_NOT_INVITED)
        update_task_status(
            task_id,
            "code_received",
            verification_code=session.verification_code,
            access_token=session.token_payload or session.access_token,
        )

        if settings["k12"].get("auto_invite", True):
            update_task_status(task_id, "k12_inviting")
            if session.provider == "mock":
                write_log("INFO", "K12 invite skipped in mock registration mode", task_id, account["id"], account["email"])
            else:
                invite_result = await request_join_workspace(
                    session.access_token,
                    task["workspace_id"],
                    settings["k12"].get("invite_mode", "request"),
                )
                if not invite_result.get("ok"):
                    status_code = invite_result.get("status_code")
                    message = invite_result.get("message")
                    raise RuntimeError(f"K12 invite failed: HTTP {status_code} {message}")
                update_account(account["id"], status=ACCOUNT_STATUS_INVITED)
                write_log("SUCCESS", "K12 workspace invite request submitted", task_id, account["id"], account["email"])

        update_task_status(task_id, "success")
        write_log("SUCCESS", f"{session.provider} registration flow completed", task_id, account["id"], account["email"])
    except Exception as exc:
        update_task_status(task_id, "failed", error_message=str(exc))
        write_log("ERROR", f"registration flow failed: {exc}", task_id, account["id"], account["email"])
    return get_task(task_id)
