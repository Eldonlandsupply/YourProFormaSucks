"""
Tests for the SQLite persistence layer (database.py).

Uses pytest's tmp_path fixture to redirect DB_PATH to a temp file,
keeping tests isolated and leaving no artifacts behind.
"""
import sqlite3

import pytest
import pandas as pd


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    """Redirect DB_PATH to a fresh temp file for each test."""
    import database
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    database.init_db()


# ── User management ───────────────────────────────────────────────────────────

def test_create_user_returns_true():
    import database
    assert database.create_user("alice", "password123") is True


def test_create_duplicate_username_returns_false():
    import database
    database.create_user("bob", "pw1")
    assert database.create_user("bob", "pw2") is False


def test_authenticate_with_correct_password():
    import database
    database.create_user("carol", "secret")
    assert database.authenticate_user("carol", "secret") is True


def test_authenticate_with_wrong_password():
    import database
    database.create_user("dave", "correct")
    assert database.authenticate_user("dave", "wrong") is False


def test_authenticate_nonexistent_user():
    import database
    assert database.authenticate_user("nobody", "pass") is False


def test_multiple_users_dont_interfere():
    import database
    database.create_user("user_a", "pass_a")
    database.create_user("user_b", "pass_b")
    assert database.authenticate_user("user_a", "pass_a") is True
    assert database.authenticate_user("user_b", "pass_b") is True
    assert database.authenticate_user("user_a", "pass_b") is False


def test_password_is_not_stored_in_plaintext():
    import database
    database.create_user("hashed-user", "correct horse battery staple")
    with database.get_connection() as connection:
        stored = connection.execute(
            "SELECT password_hash FROM users WHERE username = ?", ("hashed-user",)
        ).fetchone()[0]
    assert stored != "correct horse battery staple"
    assert stored.startswith("scrypt$")


def test_init_db_migrates_legacy_password_and_clears_plaintext():
    import database

    database.DB_PATH.unlink()
    with sqlite3.connect(database.DB_PATH) as connection:
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
            ("legacy-user", "old"),
        )

    database.init_db()

    with database.get_connection() as connection:
        columns = {
            column[1]
            for column in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        row = connection.execute(
            """
            SELECT password_hash
            FROM users
            WHERE username = ?
            """,
            ("legacy-user",),
        ).fetchone()

    assert "password" not in columns
    assert row[0].startswith("scrypt$")
    assert database.authenticate_user("legacy-user", "old") is True
    assert database.authenticate_user("legacy-user", "wrong") is False

    migrated_hash = row[0]
    database.init_db()
    with database.get_connection() as connection:
        hash_after_restart = connection.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            ("legacy-user",),
        ).fetchone()[0]
    assert hash_after_restart == migrated_hash


def test_init_db_clears_matching_dual_credentials_without_rehashing():
    import database

    database.DB_PATH.unlink()
    password_hash = database._hash_password("same-password")
    with sqlite3.connect(database.DB_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT,
                password_hash TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO users (username, password, password_hash)
            VALUES (?, ?, ?)
            """,
            ("dual-user", "same-password", password_hash),
        )

    database.init_db()

    with database.get_connection() as connection:
        columns = {
            column[1]
            for column in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        row = connection.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            ("dual-user",),
        ).fetchone()
    assert "password" not in columns
    assert row == (password_hash,)
    assert database.authenticate_user("dual-user", "same-password") is True


def test_init_db_rolls_back_when_non_null_hash_is_empty():
    import database

    database.DB_PATH.unlink()
    with sqlite3.connect(database.DB_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT,
                password_hash TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO users (username, password, password_hash)
            VALUES (?, ?, ?)
            """,
            ("invalid-hash-user", "legacy-password", ""),
        )

    with pytest.raises(database.LegacyCredentialMigrationError):
        database.init_db()

    with sqlite3.connect(database.DB_PATH) as connection:
        row = connection.execute(
            """
            SELECT password, password_hash
            FROM users
            WHERE username = ?
            """,
            ("invalid-hash-user",),
        ).fetchone()
    assert row == ("legacy-password", "")


def test_init_db_rolls_back_all_users_when_dual_credentials_conflict():
    import database

    database.DB_PATH.unlink()
    conflicting_hash = database._hash_password("current-password")
    with sqlite3.connect(database.DB_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT,
                password_hash TEXT
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO users (username, password, password_hash)
            VALUES (?, ?, ?)
            """,
            [
                ("would-migrate", "legacy-password", None),
                ("ambiguous", "stale-password", conflicting_hash),
            ],
        )

    with pytest.raises(database.LegacyCredentialMigrationError):
        database.init_db()

    with sqlite3.connect(database.DB_PATH) as connection:
        rows = connection.execute(
            """
            SELECT username, password, password_hash
            FROM users
            ORDER BY id
            """
        ).fetchall()

    assert rows == [
        ("would-migrate", "legacy-password", None),
        ("ambiguous", "stale-password", conflicting_hash),
    ]


def test_connections_wait_for_parallel_initializers():
    import database

    with database.get_connection() as connection:
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert busy_timeout == database._SQLITE_BUSY_TIMEOUT_MS


def test_session_resolves_to_owner():
    import database
    database.create_user("session-user", "password123")
    token = database.create_session("session-user")
    assert database.resolve_session(token) == "session-user"
    assert database.resolve_session("not-the-token") is None


# ── Model persistence ─────────────────────────────────────────────────────────

def test_save_model_returns_string_id():
    import database
    database.create_user("user1", "password123")
    df = pd.DataFrame({"month": [1, 2], "revenue": [1000.0, 1050.0]})
    model_id = database.save_model("user1", df)
    assert isinstance(model_id, str)
    assert len(model_id) == 32


def test_load_model_roundtrip_preserves_shape():
    import database
    database.create_user("user1", "password123")
    df = pd.DataFrame({
        "month": list(range(1, 13)),
        "revenue": [float(i * 1000) for i in range(1, 13)],
        "gross_profit": [float(i * 750) for i in range(1, 13)],
        "cac": [100.0] * 12,
    })
    model_id = database.save_model("user1", df)
    loaded = database.load_model(model_id, "user1")
    assert loaded is not None
    assert loaded.shape == df.shape
    assert list(loaded.columns) == list(df.columns)


def test_load_model_roundtrip_preserves_values():
    import database
    database.create_user("user1", "password123")
    df = pd.DataFrame({"x": [1.5, 2.5, 3.5]})
    model_id = database.save_model("user1", df)
    loaded = database.load_model(model_id, "user1")
    assert abs(loaded["x"].iloc[0] - 1.5) < 1e-9
    assert abs(loaded["x"].iloc[2] - 3.5) < 1e-9


def test_load_nonexistent_model_returns_none():
    import database
    assert database.load_model("does_not_exist_abc123", "user1") is None


def test_different_models_have_different_ids():
    import database
    database.create_user("u", "password123")
    df = pd.DataFrame({"v": [1]})
    id1 = database.save_model("u", df)
    id2 = database.save_model("u", df)
    assert id1 != id2


def test_model_cannot_be_loaded_by_another_user():
    import database
    database.create_user("owner", "password123")
    database.create_user("intruder", "password123")
    model_id = database.save_model("owner", pd.DataFrame({"v": [1]}))
    assert database.load_model(model_id, "owner") is not None
    assert database.load_model(model_id, "intruder") is None


# ── Partner requests ──────────────────────────────────────────────────────────

def test_save_partner_request_does_not_raise():
    import database
    # Should complete without exception
    database.save_partner_request(
        "Acme VC", "partner@acme.com", "We'd love to discuss a partnership."
    )


def test_save_multiple_partner_requests():
    import database
    for i in range(3):
        database.save_partner_request(f"Partner {i}", f"p{i}@example.com", "Hello")
