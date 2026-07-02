import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config
from app.config import DEFAULT_CONFIG, settings
from app.database import init_db


@pytest.fixture(autouse=True)
def isolated_database(tmp_path):
    old_path = settings["database"]["path"]
    old_config_path = config.CONFIG_PATH
    settings.clear()
    settings.update(DEFAULT_CONFIG)
    config.CONFIG_PATH = tmp_path / "config.yaml"
    config.CONFIG_PATH.write_text(
        "server:\n  host: 127.0.0.1\n  port: 8000\nauth:\n  admin_password: admin\n  token_ttl_seconds: 86400\n",
        encoding="utf-8",
    )
    settings["database"]["path"] = str(tmp_path / "k12.db")
    init_db()
    yield
    settings.clear()
    settings.update(DEFAULT_CONFIG)
    settings["database"]["path"] = old_path
    config.CONFIG_PATH = old_config_path
