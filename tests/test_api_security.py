from fastapi.testclient import TestClient

import app as application
import database


def _register_and_login(client: TestClient, username: str) -> str:
    credentials = {"username": username, "password": "secure-password"}
    assert client.post("/register", json=credentials).status_code == 200
    response = client.post("/login", json=credentials)
    assert response.status_code == 200
    return response.json()["token"]


def test_protected_routes_require_session_and_enforce_model_owner(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "app.db")

    with TestClient(application.app) as client:
        unauthenticated = client.post(
            "/generate",
            json={"monthly_revenue": 10_000},
        )
        assert unauthenticated.status_code == 401

        owner_token = _register_and_login(client, "owner")
        other_token = _register_and_login(client, "other")
        generated = client.post(
            "/generate",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"monthly_revenue": 10_000},
        )
        assert generated.status_code == 200
        model_id = generated.json()["model_id"]

        cross_owner = client.get(
            f"/export/xlsx/{model_id}",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert cross_owner.status_code == 404

        owner_export = client.get(
            f"/export/xlsx/{model_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_export.status_code == 200
        assert owner_export.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
