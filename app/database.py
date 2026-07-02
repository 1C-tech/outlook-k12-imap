from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import resolve_path, settings


_write_lock = threading.RLock()


def db_path() -> Path:
    path = resolve_path(settings["database"]["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def write_lock() -> threading.RLock:
    return _write_lock


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ms_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                client_id TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                status INTEGER NOT NULL DEFAULT 0,
                remark TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_ms_accounts_status ON ms_accounts(status);

            CREATE TABLE IF NOT EXISTS reg_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                username TEXT,
                age INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                verification_code TEXT,
                access_token TEXT,
                workspace_id TEXT,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(account_id) REFERENCES ms_accounts(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_reg_tasks_status ON reg_tasks(status);
            CREATE INDEX IF NOT EXISTS idx_reg_tasks_account ON reg_tasks(account_id);

            CREATE TABLE IF NOT EXISTS reg_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                account_id INTEGER,
                email TEXT,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                detail TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_logs_task ON reg_logs(task_id);
            CREATE INDEX IF NOT EXISTS idx_logs_level ON reg_logs(level);
            CREATE INDEX IF NOT EXISTS idx_logs_created ON reg_logs(created_at);

            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None

