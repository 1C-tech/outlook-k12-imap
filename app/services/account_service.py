from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..database import connect, row_to_dict, write_lock


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class ImportResult:
    count: int = 0
    updated: int = 0
    duplicated: int = 0
    failed: int = 0
    errors: list[dict] = field(default_factory=list)


ACCOUNT_STATUS_UNREGISTERED = 0
ACCOUNT_STATUS_REGISTERED_NOT_INVITED = 1
ACCOUNT_STATUS_INVITED = 2

ACCOUNT_STATUS_LABELS = {
    ACCOUNT_STATUS_UNREGISTERED: "未注册",
    ACCOUNT_STATUS_REGISTERED_NOT_INVITED: "注册完成未邀请",
    ACCOUNT_STATUS_INVITED: "注册完成并邀请成功",
}


def parse_account_line(line: str) -> tuple[str, str, str, str]:
    parts = [item.strip() for item in line.split("----")]
    if len(parts) != 4:
        raise ValueError("expected format: email----password----client_id----refresh_token")
    email, password, client_id, refresh_token = parts
    if not EMAIL_RE.match(email):
        raise ValueError("invalid email")
    if not password or not client_id or not refresh_token:
        raise ValueError("password, client_id and refresh_token are required")
    return email.lower(), password, client_id, refresh_token


def import_accounts(raw_text: str) -> ImportResult:
    result = ImportResult()
    with write_lock():
        with connect() as conn:
            for line_no, raw in enumerate((raw_text or "").splitlines(), 1):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    email, password, client_id, refresh_token = parse_account_line(line)
                    existed = conn.execute("SELECT 1 FROM ms_accounts WHERE email = ?", (email,)).fetchone() is not None
                    conn.execute(
                        """
                        INSERT INTO ms_accounts(email, password, client_id, refresh_token, status)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(email) DO UPDATE SET
                            password = excluded.password,
                            client_id = excluded.client_id,
                            refresh_token = excluded.refresh_token,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (email, password, client_id, refresh_token, ACCOUNT_STATUS_UNREGISTERED),
                    )
                    if existed:
                        result.duplicated += 1
                        result.updated += 1
                    else:
                        result.count += 1
                except Exception as exc:
                    result.failed += 1
                    result.errors.append({"line": line_no, "message": str(exc), "raw": raw})
    return result


def list_accounts(page: int = 1, page_size: int = 50, search: str | None = None, status: int | None = None) -> dict:
    page = max(1, int(page))
    page_size = min(200, max(1, int(page_size)))
    where = []
    params: list = []
    if search:
        where.append("email LIKE ?")
        params.append(f"%{search}%")
    if status is not None:
        where.append("status = ?")
        params.append(status)
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM ms_accounts {where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT id, email, status, remark, created_at, updated_at
            FROM ms_accounts
            {where_sql}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
    data = []
    for row in rows:
        item = dict(row)
        item["status_label"] = ACCOUNT_STATUS_LABELS.get(int(item["status"]), "未知")
        data.append(item)
    return {"data": data, "total": total, "page": page, "page_size": page_size, "status_labels": ACCOUNT_STATUS_LABELS}


def list_account_ids_by_status(status: int, limit: int | None = None) -> list[int]:
    sql = "SELECT id FROM ms_accounts WHERE status = ? ORDER BY id ASC"
    params: list = [int(status)]
    if limit is not None and int(limit) > 0:
        sql += " LIMIT ?"
        params.append(int(limit))
    with connect() as conn:
        return [int(row["id"]) for row in conn.execute(sql, params).fetchall()]


def get_account(account_id: int, include_secret: bool = False) -> dict | None:
    fields = "*" if include_secret else "id, email, status, remark, created_at, updated_at"
    with connect() as conn:
        account = row_to_dict(conn.execute(f"SELECT {fields} FROM ms_accounts WHERE id = ?", (account_id,)).fetchone())
        if account:
            account["status_label"] = ACCOUNT_STATUS_LABELS.get(int(account["status"]), "未知")
        return account


def update_account(account_id: int, status: int | None = None, remark: str | None = None) -> bool:
    updates = []
    params: list = []
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if remark is not None:
        updates.append("remark = ?")
        params.append(remark)
    if not updates:
        return True
    updates.append("updated_at = CURRENT_TIMESTAMP")
    with write_lock():
        with connect() as conn:
            cur = conn.execute(f"UPDATE ms_accounts SET {', '.join(updates)} WHERE id = ?", [*params, account_id])
            return cur.rowcount > 0


def delete_accounts(ids: list[int]) -> int:
    clean_ids = [int(item) for item in ids]
    if not clean_ids:
        return 0
    placeholders = ",".join("?" for _ in clean_ids)
    with write_lock():
        with connect() as conn:
            cur = conn.execute(f"DELETE FROM ms_accounts WHERE id IN ({placeholders})", clean_ids)
            return cur.rowcount
