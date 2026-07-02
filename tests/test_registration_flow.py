import pytest

from app.database import init_db
from app.config import settings
from app.services.account_service import import_accounts
from app.services.state_machine import create_tasks, get_task, run_task
from app.services.openai_registration import OpenAIRegistrationError, submit_callback_url


@pytest.mark.asyncio
async def test_mock_registration_flow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    init_db()
    import_accounts("flow@example.com----pwd----cid----rt")
    task_ids = create_tasks([1])
    assert len(task_ids) == 1
    final = await run_task(task_ids[0])
    assert final["status"] == "success"
    assert final["verification_code"]
    assert final["access_token"].startswith("mock_at_")


@pytest.mark.asyncio
async def test_openai_registration_fails_clearly_without_auth_core(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings["registration"]["provider"] = "openai"
    settings["registration"]["auth_core_path"] = str(tmp_path / "missing-openai-cpa")
    init_db()
    import_accounts("real@example.com----pwd----cid----rt")
    task_ids = create_tasks([1])
    final = await run_task(task_ids[0])
    assert final["status"] == "failed"
    assert "auth_core could not be loaded" in final["error_message"]


def test_submit_callback_url_rejects_state_mismatch():
    with pytest.raises(OpenAIRegistrationError, match="state mismatch"):
        submit_callback_url(
            "http://localhost:1455/auth/callback?code=abc&state=actual",
            expected_state="expected",
            code_verifier="verifier",
        )
