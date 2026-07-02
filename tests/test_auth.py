from fastapi.testclient import TestClient

from app.main import app


def test_login_and_authenticated_request():
    client = TestClient(app)
    token = client.post("/api/auth/login", json={"password": "admin"}).json()["token"]
    resp = client.get("/api/accounts", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200

