"""
Tests for the SQLite persistence layer (database.py).

Uses pytest's tmp_path fixture to redirect DB_PATH to a temp file,
keeping tests isolated and leaving no artifacts behind.
"""
import io
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


# ── Model persistence ─────────────────────────────────────────────────────────

def test_save_model_returns_string_id():
    import database
    df = pd.DataFrame({"month": [1, 2], "revenue": [1000.0, 1050.0]})
    model_id = database.save_model("user1", df)
    assert isinstance(model_id, str)
    assert len(model_id) == 16  # os.urandom(8).hex() = 16 chars


def test_load_model_roundtrip_preserves_shape():
    import database
    df = pd.DataFrame({
        "month": list(range(1, 13)),
        "revenue": [float(i * 1000) for i in range(1, 13)],
        "gross_profit": [float(i * 750) for i in range(1, 13)],
        "cac": [100.0] * 12,
    })
    model_id = database.save_model("user1", df)
    loaded = database.load_model(model_id)
    assert loaded is not None
    assert loaded.shape == df.shape
    assert list(loaded.columns) == list(df.columns)


def test_load_model_roundtrip_preserves_values():
    import database
    df = pd.DataFrame({"x": [1.5, 2.5, 3.5]})
    model_id = database.save_model("user1", df)
    loaded = database.load_model(model_id)
    assert abs(loaded["x"].iloc[0] - 1.5) < 1e-9
    assert abs(loaded["x"].iloc[2] - 3.5) < 1e-9


def test_load_nonexistent_model_returns_none():
    import database
    assert database.load_model("does_not_exist_abc123") is None


def test_different_models_have_different_ids():
    import database
    df = pd.DataFrame({"v": [1]})
    id1 = database.save_model("u", df)
    id2 = database.save_model("u", df)
    assert id1 != id2


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
