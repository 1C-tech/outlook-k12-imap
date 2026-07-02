from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.yaml"

DEFAULT_CONFIG: dict[str, Any] = {
    "server": {"host": "127.0.0.1", "port": 8000},
    "auth": {"admin_password": "admin", "token_ttl_seconds": 86400},
    "database": {"path": "data/k12.db"},
    "k12": {
        "workspace_id": "631e1603-06cf-4f0b-b79b-d09fbfcfe98d",
        "invite_mode": "request",
        "auto_invite": True,
    },
    "registration": {
        "provider": "mock",
        "concurrency": 1,
        "proxy": "",
        "auth_core_path": "F:/game/openai-cpa/openai-cpa-main",
        "max_otp_retries": 3,
        "otp_poll_attempts": 20,
        "otp_poll_interval_seconds": 3,
        "http_retries": 2,
        "http_timeout_seconds": 30,
        "ssl_verify": True,
    },
    "imap": {
        "host": "outlook.office365.com",
        "port": 993,
        "timeout_seconds": 20,
        "folders": ["INBOX", "Junk"],
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "chatai_base_url": "https://mail.chatai.codes",
        "use_chatai_fetcher": True,
        "local_fallback": False,
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False), encoding="utf-8")
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    config = _deep_merge(DEFAULT_CONFIG, raw)
    env_password = os.getenv("K12_ADMIN_PASSWORD")
    if env_password:
        config["auth"]["admin_password"] = env_password
    return config


def save_config(config: dict[str, Any]) -> dict[str, Any]:
    merged = _deep_merge(DEFAULT_CONFIG, config)
    CONFIG_PATH.write_text(yaml.safe_dump(merged, sort_keys=False, allow_unicode=True), encoding="utf-8")
    settings.clear()
    settings.update(merged)
    return merged


settings = load_config()


def reload_settings() -> dict[str, Any]:
    settings.clear()
    settings.update(load_config())
    return settings


def resolve_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path
