from fastapi.testclient import TestClient

from app.database import connect
from app.main import app


def _client_with_token():
    client = TestClient(app)
    token = client.post("/api/auth/login", json={"password": "admin"}).json()["token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_import_create_start_and_logs():
    client = _client_with_token()
    imported = client.post(
        "/api/accounts/import",
        json={"raw_text": "api@example.com----pwd----cid----rt"},
    )
    assert imported.status_code == 200
    assert imported.json()["count"] == 1

    accounts = client.get("/api/accounts").json()["data"]
    account_id = accounts[0]["id"]
    created = client.post("/api/tasks", json={"account_ids": [account_id]})
    assert created.status_code == 200
    task_id = created.json()["task_ids"][0]

    started = client.post(f"/api/tasks/{task_id}/start")
    assert started.status_code == 200
    task = client.get(f"/api/tasks/{task_id}").json()
    assert task["status"] == "success"

    logs = client.get("/api/logs", params={"task_id": task_id}).json()
    assert logs["total"] >= 5

    accounts_after = client.get("/api/accounts", params={"status": 1}).json()
    assert accounts_after["total"] >= 1

    cleared = client.delete("/api/logs")
    assert cleared.status_code == 200
    assert cleared.json()["deleted"] >= 5
    assert client.get("/api/logs").json()["total"] == 0


def test_run_by_account_status_creates_and_runs_matching_accounts():
    client = _client_with_token()
    imported = client.post(
        "/api/accounts/import",
        json={"raw_text": "a@example.com----pwd----cid----rt\nb@example.com----pwd----cid----rt"},
    )
    assert imported.status_code == 200

    started = client.post("/api/tasks/run_by_account_status", json={"account_status": 0, "concurrency": 2})
    assert started.status_code == 200
    payload = started.json()
    assert payload["created"] == 2
    assert len(payload["task_ids"]) == 2

    remaining = client.get("/api/accounts", params={"status": 0}).json()
    assert remaining["total"] == 0
    registered = client.get("/api/accounts", params={"status": 1}).json()
    assert registered["total"] >= 2


def test_run_unfinished_registers_and_invites_pending_accounts():
    client = _client_with_token()
    imported = client.post(
        "/api/accounts/import",
        json={"raw_text": "new@example.com----pwd----cid----rt\ninvite@example.com----pwd----cid----rt"},
    )
    assert imported.status_code == 200
    with connect() as conn:
        invite_id = conn.execute("SELECT id FROM ms_accounts WHERE email = ?", ("invite@example.com",)).fetchone()["id"]
        conn.execute("UPDATE ms_accounts SET status = 1 WHERE id = ?", (invite_id,))
        conn.execute(
            """
            INSERT INTO reg_tasks(account_id, email, status, access_token, workspace_id)
            VALUES (?, ?, 'success', ?, ?)
            """,
            (invite_id, "invite@example.com", "mock_at_existing", "631e1603-06cf-4f0b-b79b-d09fbfcfe98d"),
        )

    started = client.post("/api/tasks/run_unfinished")
    assert started.status_code == 200
    assert started.json()["status"] == "success"

    unregistered = client.get("/api/accounts", params={"status": 0}).json()
    assert unregistered["total"] == 0
    registered_not_invited = client.get("/api/accounts", params={"status": 1}).json()
    assert registered_not_invited["total"] >= 1
    invited = client.get("/api/accounts", params={"status": 2}).json()
    assert invited["total"] >= 1


def test_settings_roundtrip():
    client = _client_with_token()
    current = client.get("/api/settings").json()
    current["registration"]["concurrency"] = 2
    saved = client.put("/api/settings", json=current)
    assert saved.status_code == 200
    client.post("/api/settings/reload")
    assert client.get("/api/settings").json()["registration"]["concurrency"] == 2
