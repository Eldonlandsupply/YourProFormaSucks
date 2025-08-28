"""
Simple SQLite persistence layer for YourProformaSucks.

This module abstracts away the details of storing users, generated
pro formas and partner inquiries.  It uses Python's built‑in
``sqlite3`` module and creates tables on startup if they do not
already exist.  The goal is to make it easy to swap out this file
for something more robust (e.g. SQLAlchemy, PostgreSQL) in the
future while keeping the rest of the application agnostic.
"""

import os
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

# Database path lives alongside this file
DB_PATH = Path(os.path.dirname(__file__)) / "app.db"


def get_connection() -> sqlite3.Connection:
    """Open a connection to the SQLite database.

    Using ``check_same_thread=False`` allows the connection to be
    shared across asyncio threads in FastAPI.
    """
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db() -> None:
    """Initialise database tables if they do not exist."""
    conn = get_connection()
    cur = conn.cursor()
    # Users table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )
        """
    )
    # Models table: id, user, csv_data
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS models (
            id TEXT PRIMARY KEY,
            username TEXT,
            csv_data TEXT
        )
        """
    )
    # Partner requests table
    cur.execute(
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
    conn.commit()
    conn.close()


def create_user(username: str, password: str) -> bool:
    """Create a new user.  Returns False if the username already exists."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def authenticate_user(username: str, password: str) -> bool:
    """Return True if the given credentials match a user."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT password FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    return row is not None and row[0] == password


def save_model(username: str, df: pd.DataFrame) -> str:
    """Persist a DataFrame and return its identifier."""
    model_id = os.urandom(8).hex()
    csv_data = df.to_csv(index=False)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO models (id, username, csv_data) VALUES (?, ?, ?)",
        (model_id, username, csv_data),
    )
    conn.commit()
    conn.close()
    return model_id


def load_model(model_id: str) -> Optional[pd.DataFrame]:
    """Load a DataFrame by model ID or return None if not found."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT csv_data FROM models WHERE id = ?", (model_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    csv_data = row[0]
    from io import StringIO
    return pd.read_csv(StringIO(csv_data))


def save_partner_request(name: str, email: str, message: str) -> None:
    """Save a partner inquiry."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO partner_requests (name, email, message) VALUES (?, ?, ?)",
        (name, email, message),
    )
    conn.commit()
    conn.close()