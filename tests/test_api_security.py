import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
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


def test_mixed_case_bearer_scheme_is_accepted(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "app.db")

    with TestClient(application.app) as client:
        token = _register_and_login(client, "mixed-case-user")
        response = client.post(
            "/generate",
            headers={"Authorization": f"bEaReR {token}"},
            json={"monthly_revenue": 10_000},
        )

    assert response.status_code == 200


def test_malformed_bearer_headers_are_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "app.db")

    with TestClient(application.app) as client:
        token = _register_and_login(client, "strict-header-user")
        malformed_headers = [
            f"Basic {token}",
            "Bearer",
            "Bearer ",
            f"Bearer  {token}",
            f"Bearer\t{token}",
            f" Bearer {token}",
            f"Bearer {token} ",
            f"Bearer {token}.",
            f"Bearer {token}=",
            f"Bearer {token[:-1]}",
        ]

        for authorization in malformed_headers:
            response = client.post(
                "/generate",
                headers={"Authorization": authorization},
                json={"monthly_revenue": 10_000},
            )
            assert response.status_code == 401, authorization


def test_duplicate_authorization_headers_are_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "app.db")

    with TestClient(application.app) as client:
        token = _register_and_login(client, "duplicate-header-user")
        for headers in [
            [
                ("Authorization", f"Bearer {token}"),
                ("Authorization", "Basic bad"),
            ],
            [
                ("Authorization", "Basic bad"),
                ("Authorization", f"Bearer {token}"),
            ],
            [
                ("Authorization", f"Bearer {token}"),
                ("Authorization", f"Bearer {token}"),
            ],
        ]:
            response = client.post(
                "/generate",
                headers=headers,
                json={"monthly_revenue": 10_000},
            )
            assert response.status_code == 401


def test_invalid_and_expired_tokens_are_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "app.db")

    with TestClient(application.app) as client:
        invalid = client.post(
            "/generate",
            headers={"Authorization": f"Bearer {'A' * 43}"},
            json={"monthly_revenue": 10_000},
        )
        assert invalid.status_code == 401

        token = _register_and_login(client, "expired-session-user")
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expired_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        with database.get_connection() as connection:
            connection.execute(
                "UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
                (expired_at.isoformat(), token_hash),
            )

        expired = client.post(
            "/generate",
            headers={"Authorization": f"Bearer {token}"},
            json={"monthly_revenue": 10_000},
        )
        assert expired.status_code == 401


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("legacy-api-user", "old"),
        ("", ""),
        ("u" * 101, "p" * 257),
    ],
)
def test_legacy_user_can_log_in_after_startup_migration(
    monkeypatch,
    tmp_path,
    username,
    password,
):
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (username, password),
        )

    with TestClient(application.app) as client:
        login = client.post(
            "/login",
            json={"username": username, "password": password},
        )
        assert login.status_code == 200
        token = login.json()["token"]
        protected = client.post(
            "/generate",
            headers={"Authorization": f"Bearer {token}"},
            json={"monthly_revenue": 10_000},
        )
        assert protected.status_code == 200

    with database.get_connection() as connection:
        columns = {
            column[1]
            for column in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        row = connection.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    assert "password" not in columns
    assert row[0].startswith("scrypt$")


@pytest.mark.parametrize(
    "credentials",
    [
        {"username": "", "password": "password123"},
        {"username": "u" * 101, "password": "password123"},
        {"username": "new-user", "password": ""},
        {"username": "new-user", "password": "short"},
        {"username": "new-user", "password": "p" * 257},
    ],
)
def test_registration_rejects_credentials_outside_policy(
    monkeypatch, tmp_path, credentials
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "app.db")

    with TestClient(application.app) as client:
        response = client.post("/register", json=credentials)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "credentials",
    [
        {"username": "u", "password": "p" * 8},
        {"username": "u" * 100, "password": "p" * 256},
    ],
)
def test_registration_accepts_credentials_at_policy_boundaries(
    monkeypatch, tmp_path, credentials
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "app.db")

    with TestClient(application.app) as client:
        response = client.post("/register", json=credentials)

    assert response.status_code == 200
