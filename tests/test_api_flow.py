from fastapi.testclient import TestClient

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


def test_settings_roundtrip():
    client = _client_with_token()
    current = client.get("/api/settings").json()
    current["registration"]["concurrency"] = 2
    saved = client.put("/api/settings", json=current)
    assert saved.status_code == 200
    client.post("/api/settings/reload")
    assert client.get("/api/settings").json()["registration"]["concurrency"] == 2
