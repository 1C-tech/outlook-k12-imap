import pytest

from app.database import init_db
from app.config import settings
from app.services.account_service import import_accounts
from app.services import state_machine
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
    assert "无法加载 OpenAI auth_core" in final["error_message"]


def test_submit_callback_url_rejects_state_mismatch():
    with pytest.raises(OpenAIRegistrationError, match="state 不匹配"):
        submit_callback_url(
            "http://localhost:1455/auth/callback?code=abc&state=actual",
            expected_state="expected",
            code_verifier="verifier",
        )


@pytest.mark.asyncio
async def test_run_unfinished_creates_registration_tasks_inside_concurrency_slots(monkeypatch):
    settings["registration"]["concurrency"] = 1
    import_accounts(
        "one@example.com----pwd----cid----rt\n"
        "two@example.com----pwd----cid----rt\n"
        "three@example.com----pwd----cid----rt"
    )

    original_create_tasks = state_machine.create_tasks
    create_batches: list[list[int]] = []

    def tracking_create_tasks(account_ids, username=None, age=None):
        create_batches.append(list(account_ids))
        return original_create_tasks(account_ids, username, age)

    async def fake_run_task(task_id: int):
        return {"id": task_id, "status": "success"}

    monkeypatch.setattr(state_machine, "create_tasks", tracking_create_tasks)
    monkeypatch.setattr(state_machine, "run_task", fake_run_task)

    result = await state_machine.run_unfinished_accounts()

    assert result["concurrency"] == 1
    assert result["created"] == 3
    assert create_batches == [[1], [2], [3]]
