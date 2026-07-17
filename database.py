"""SQLite persistence for the pro forma prototype.

This module intentionally keeps authentication and ownership enforcement close
to persistence so callers cannot load a model without its owner identity.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Optional

import pandas as pd

DB_PATH = Path(os.path.dirname(__file__)) / "app.db"
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SESSION_TTL_HOURS = 12


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, check_same_thread=False)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT
            )
            """
        )
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        if "password_hash" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS models (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                csv_data TEXT NOT NULL,
                FOREIGN KEY (username) REFERENCES users(username)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (username) REFERENCES users(username)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS partner_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT,
                message TEXT,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def _hash_password(password: str, salt: Optional[bytes] = None) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("password must not be empty")
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=32,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${derived.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, expected_hex = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(expected_hex)),
        )
        return hmac.compare_digest(actual.hex(), expected_hex)
    except (TypeError, ValueError):
        return False


def create_user(username: str, password: str) -> bool:
    password_hash = _hash_password(password)
    try:
        with get_connection() as connection:
            connection.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def authenticate_user(username: str, password: str) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    return bool(row and row[0] and _verify_password(password, row[0]))


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=_SESSION_TTL_HOURS)
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO sessions (token_hash, username, expires_at) VALUES (?, ?, ?)",
            (token_hash, username, expires_at.isoformat()),
        )
    return token


def resolve_session(token: str) -> Optional[str]:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    with get_connection() as connection:
        row = connection.execute(
            "SELECT username, expires_at FROM sessions WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        if row is None:
            return None
        try:
            expires_at = datetime.fromisoformat(row[1])
        except ValueError:
            return None
        if expires_at <= now:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
            return None
        return str(row[0])


def save_model(username: str, df: pd.DataFrame) -> str:
    model_id = secrets.token_hex(16)
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO models (id, username, csv_data) VALUES (?, ?, ?)",
            (model_id, username, df.to_csv(index=False)),
        )
    return model_id


def load_model(model_id: str, username: str) -> Optional[pd.DataFrame]:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT csv_data FROM models WHERE id = ? AND username = ?",
            (model_id, username),
        ).fetchone()
    return None if row is None else pd.read_csv(StringIO(row[0]))


def save_partner_request(name: str, email: str, message: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO partner_requests (name, email, message) VALUES (?, ?, ?)",
            (name, email, message),
        )
