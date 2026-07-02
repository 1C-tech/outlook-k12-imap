from __future__ import annotations

import json
from datetime import datetime

from ..database import connect, write_lock


def write_log(
    level: str,
    message: str,
    task_id: int | None = None,
    account_id: int | None = None,
    email: str | None = None,
    detail: dict | str | None = None,
) -> int:
    if isinstance(detail, dict):
        detail = json.dumps(detail, ensure_ascii=False)
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO reg_logs(task_id, account_id, email, level, message, detail)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (task_id, account_id, email, level.upper(), message, detail),
        )
        return int(cur.lastrowid)


def query_logs(
    page: int = 1,
    page_size: int = 50,
    level: str | None = None,
    task_id: int | None = None,
    email: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    page = max(1, int(page))
    page_size = min(200, max(1, int(page_size)))
    where = []
    params: list = []
    if level:
        where.append("level = ?")
        params.append(level.upper())
    if task_id:
        where.append("task_id = ?")
        params.append(task_id)
    if email:
        where.append("email LIKE ?")
        params.append(f"%{email}%")
    if start:
        where.append("created_at >= ?")
        params.append(start)
    if end:
        where.append("created_at <= ?")
        params.append(end)
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM reg_logs {where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT * FROM reg_logs
            {where_sql}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
    return {"data": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}


def get_log(log_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM reg_logs WHERE id = ?", (log_id,)).fetchone()
        return dict(row) if row else None


def clear_logs() -> int:
    with write_lock():
        with connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM reg_logs").fetchone()[0]
            conn.execute("DELETE FROM reg_logs")
            return int(total)


def stats(task_id: int | None = None) -> dict:
    where = "WHERE task_id = ?" if task_id else ""
    params = [task_id] if task_id else []
    with connect() as conn:
        rows = conn.execute(f"SELECT level, COUNT(*) count FROM reg_logs {where} GROUP BY level", params).fetchall()
        total = conn.execute(f"SELECT COUNT(*) FROM reg_logs {where}", params).fetchone()[0]
    result = {"total": total, "generated_at": datetime.utcnow().isoformat() + "Z"}
    result.update({row["level"]: row["count"] for row in rows})
    return result
